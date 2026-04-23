#include "strict_queue_greedy_scheduler.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <vector>

#include "path_utils.h"

namespace flsim {
namespace {

constexpr int kPerTypeCandidateLimit = 8;

enum class PathType {
    TorTor = 0,
    TorTorTor = 1,
    TorTorTorTor = 2,
    TorEpsTor = 3,
    TorTorEpsTor = 4,
    TorEpsTorTor = 5,
    Unknown = 6,
};

// Path-template switches for strict_queue_greedy.
// Edit these booleans directly to enable/disable each template family.
constexpr bool kEnableTorTor = true;          // ToR -> ToR
constexpr bool kEnableTorTorTor = true;       // ToR -> ToR -> ToR
constexpr bool kEnableTorTorTorTor = true;    // ToR -> ToR -> ToR -> ToR
constexpr bool kEnableTorEpsTor = true;       // ToR -> EPS -> ToR
constexpr bool kEnableTorTorEpsTor = false;    // ToR -> ToR -> EPS -> ToR
constexpr bool kEnableTorEpsTorTor = false;    // ToR -> EPS -> ToR -> ToR

struct PathPrediction {
    double serviceStartTime = 0.0;
    double finishTime = 0.0;
    double bottleneckRate = 0.0;
};

PathType inferPathType(const CandidatePath& path, int numTor) {
    const auto& n = path.nodes;
    if (n.size() == 2) {
        return PathType::TorTor;
    }
    if (n.size() == 3) {
        return (n[1] < numTor) ? PathType::TorTorTor : PathType::TorEpsTor;
    }
    if (n.size() == 4) {
        if (n[1] < numTor && n[2] < numTor) {
            return PathType::TorTorTorTor;
        }
        if (n[1] < numTor && n[2] >= numTor) {
            return PathType::TorTorEpsTor;
        }
        if (n[1] >= numTor && n[2] < numTor) {
            return PathType::TorEpsTorTor;
        }
    }
    return PathType::Unknown;
}

bool isPathTypeEnabled(PathType type) {
    switch (type) {
        case PathType::TorTor:
            return kEnableTorTor;
        case PathType::TorTorTor:
            return kEnableTorTorTor;
        case PathType::TorTorTorTor:
            return kEnableTorTorTorTor;
        case PathType::TorEpsTor:
            return kEnableTorEpsTor;
        case PathType::TorTorEpsTor:
            return kEnableTorTorEpsTor;
        case PathType::TorEpsTorTor:
            return kEnableTorEpsTorTor;
        case PathType::Unknown:
        default:
            return false;
    }
}

std::vector<CandidatePath> enumerateEnabledTemplateCandidates(
    int s,
    int t,
    const std::vector<std::vector<double>>& capacity,
    int numTor,
    int numEps) {
    const auto raw = enumerateCandidatePaths(s, t, capacity, numTor, numEps);
    std::vector<CandidatePath> filtered;
    filtered.reserve(raw.size());
    for (const auto& path : raw) {
        if (!isPathTypeEnabled(inferPathType(path, numTor))) {
            continue;
        }
        filtered.push_back(path);
    }
    return filtered;
}

struct PathHeuristic {
    CandidatePath path;
    double readyTime = 0.0;
    double bottleneckRate = 0.0;
};

PathHeuristic buildPathHeuristic(const CandidatePath& path,
                                 const std::vector<std::vector<double>>& capacity,
                                 const std::vector<std::vector<double>>& freeTime) {
    PathHeuristic h;
    h.path = path;
    h.readyTime = 0.0;
    h.bottleneckRate = std::numeric_limits<double>::infinity();

    for (const auto& edge : pathToEdges(path)) {
        const int u = edge.first;
        const int v = edge.second;
        const double cap = capacity[u][v];
        if (cap <= 0.0) {
            throw std::runtime_error("Candidate path contains an edge with non-positive capacity.");
        }
        if (freeTime[u][v] > h.readyTime) {
            h.readyTime = freeTime[u][v];
        }
        if (cap < h.bottleneckRate) {
            h.bottleneckRate = cap;
        }
    }
    return h;
}

std::vector<PathHeuristic> pruneCandidatesByType(const std::vector<CandidatePath>& candidates,
                                                 const std::vector<std::vector<double>>& capacity,
                                                 const std::vector<std::vector<double>>& freeTime,
                                                 int numTor) {
    std::vector<PathHeuristic> buckets[7];
    for (const auto& path : candidates) {
        const auto type = inferPathType(path, numTor);
        buckets[static_cast<int>(type)].push_back(buildPathHeuristic(path, capacity, freeTime));
    }

    std::vector<PathHeuristic> pruned;
    for (int t = 0; t < 7; ++t) {
        auto& b = buckets[t];
        std::sort(b.begin(), b.end(), [](const PathHeuristic& a, const PathHeuristic& b) {
            if (a.readyTime != b.readyTime) {
                return a.readyTime < b.readyTime;
            }
            if (a.bottleneckRate != b.bottleneckRate) {
                return a.bottleneckRate > b.bottleneckRate;
            }
            return a.path.nodes.size() < b.path.nodes.size();
        });

        const int keep = (t == static_cast<int>(PathType::Unknown))
                             ? static_cast<int>(b.size())
                             : std::min(kPerTypeCandidateLimit, static_cast<int>(b.size()));
        for (int i = 0; i < keep; ++i) {
            pruned.push_back(b[i]);
        }
    }
    return pruned;
}

void commitPathReservation(const CandidatePath& path,
                           double finishTime,
                           std::vector<std::vector<double>>& freeTime) {
    for (const auto& edge : pathToEdges(path)) {
        freeTime[edge.first][edge.second] = finishTime;
    }
}

}  // namespace

void StrictQueueGreedyScheduler::prepare(const SchedulerContext& ctx) const {
    if (cachedCapacity_ == &ctx.capacity &&
        cachedNumTor_ == ctx.numTor &&
        cachedNumEps_ == ctx.numEps &&
        !cachedPairCandidates_.empty()) {
        return;
    }

    cachedCapacity_ = &ctx.capacity;
    cachedNumTor_ = ctx.numTor;
    cachedNumEps_ = ctx.numEps;
    cachedPairCandidates_.assign(
        ctx.numTor, std::vector<std::vector<CandidatePath>>(ctx.numTor));

    for (int s = 0; s < ctx.numTor; ++s) {
        for (int t = 0; t < ctx.numTor; ++t) {
            if (s == t) {
                continue;
            }
            cachedPairCandidates_[s][t] =
                enumerateEnabledTemplateCandidates(s, t, ctx.capacity, ctx.numTor, ctx.numEps);
        }
    }
}

std::string StrictQueueGreedyScheduler::name() const {
    return "ocs_eps_pruned";
}

std::vector<ScheduledFlow> StrictQueueGreedyScheduler::scheduleJob(const Job& job,
                                                                   const SchedulerContext& ctx) const {
    prepare(ctx);

    std::vector<ScheduledFlow> scheduled;
    std::vector<std::vector<double>> localFreeTime = ctx.currentFreeTime;

    for (const auto& flow : job.flows) {
        ScheduledFlow best;
        best.flow = flow;

        if (flow.torSrc == flow.torDst) {
            best.sameTorBypass = true;
            best.corePath = {flow.torSrc};
            best.serviceStartTime = flow.startTime;
            best.finishTime = flow.startTime;
            best.bottleneckRate = std::numeric_limits<double>::infinity();
            scheduled.push_back(best);
            continue;
        }

        const auto& candidates = cachedPairCandidates_[flow.torSrc][flow.torDst];
        if (candidates.empty()) {
            throw std::runtime_error("No candidate path found for flowId=" + std::to_string(flow.flowId) +
                                     " torSrc=" + std::to_string(flow.torSrc) +
                                     " torDst=" + std::to_string(flow.torDst));
        }
        const auto evalCandidates = pruneCandidatesByType(candidates, ctx.capacity, localFreeTime, ctx.numTor);

        bool chosen = false;
        CandidatePath bestPath;
        PathPrediction bestPred;
        bestPred.finishTime = std::numeric_limits<double>::infinity();

        for (const auto& cand : evalCandidates) {
            PathPrediction pred;
            pred.serviceStartTime = std::max(flow.startTime, cand.readyTime);
            pred.bottleneckRate = cand.bottleneckRate;
            pred.finishTime = pred.serviceStartTime + flow.bytes / pred.bottleneckRate;
            if (pred.finishTime > bestPred.finishTime + 1e-12) {
                continue;
            }
            if (!chosen ||
                pred.finishTime < bestPred.finishTime - 1e-12 ||
                (std::fabs(pred.finishTime - bestPred.finishTime) <= 1e-12 &&
                 pred.serviceStartTime < bestPred.serviceStartTime - 1e-12) ||
                (std::fabs(pred.finishTime - bestPred.finishTime) <= 1e-12 &&
                 std::fabs(pred.serviceStartTime - bestPred.serviceStartTime) <= 1e-12 &&
                 cand.path.nodes.size() < bestPath.nodes.size())) {
                chosen = true;
                bestPath = cand.path;
                bestPred = pred;
            }
        }

        best.sameTorBypass = false;
        best.corePath = bestPath.nodes;
        best.serviceStartTime = bestPred.serviceStartTime;
        best.finishTime = bestPred.finishTime;
        best.bottleneckRate = bestPred.bottleneckRate;
        scheduled.push_back(best);

        commitPathReservation(bestPath, best.finishTime, localFreeTime);
    }

    return scheduled;
}

}  // namespace flsim
