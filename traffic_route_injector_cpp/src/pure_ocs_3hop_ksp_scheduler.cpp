#include "pure_ocs_3hop_ksp_scheduler.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <queue>
#include <stdexcept>
#include <vector>

#include "path_utils.h"

namespace flsim {
namespace {

constexpr int kPerTypeCandidateLimit = 8;
constexpr int kMaxSearchedHops = 3;

enum class PathType {
    TorTor = 0,
    TorTorTor = 1,
    TorTorTorTor = 2,
    TorEpsTor = 3,
    TorTorEpsTor = 4,
    TorEpsTorTor = 5,
    Unknown = 6,
};

struct PathHeuristic {
    CandidatePath path;
    double readyTime = 0.0;
    double bottleneckRate = 0.0;
};

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
        auto& bucket = buckets[t];
        std::sort(bucket.begin(), bucket.end(), [](const PathHeuristic& a, const PathHeuristic& b) {
            if (a.readyTime != b.readyTime) {
                return a.readyTime < b.readyTime;
            }
            if (a.bottleneckRate != b.bottleneckRate) {
                return a.bottleneckRate > b.bottleneckRate;
            }
            return a.path.nodes.size() < b.path.nodes.size();
        });

        const int keep = (t == static_cast<int>(PathType::Unknown))
                             ? static_cast<int>(bucket.size())
                             : std::min(kPerTypeCandidateLimit, static_cast<int>(bucket.size()));
        for (int i = 0; i < keep; ++i) {
            pruned.push_back(bucket[i]);
        }
    }
    return pruned;
}

std::vector<CandidatePath> enumerateTemplateOcsPaths(int s,
                                                     int t,
                                                     const std::vector<std::vector<double>>& capacity,
                                                     int numTor,
                                                     int maxHops,
                                                     int maxCandidates) {
    auto raw = enumerateCandidatePaths(s, t, capacity, numTor, 0);

    std::vector<CandidatePath> filtered;
    filtered.reserve(raw.size());
    for (const auto& p : raw) {
        const int hops = static_cast<int>(p.nodes.size()) - 1;
        if (hops <= 0 || hops > maxHops) {
            continue;
        }
        bool torOnly = true;
        for (const int node : p.nodes) {
            if (node < 0 || node >= numTor) {
                torOnly = false;
                break;
            }
        }
        if (!torOnly) {
            continue;
        }
        filtered.push_back(p);
        if (static_cast<int>(filtered.size()) >= maxCandidates) {
            break;
        }
    }
    return filtered;
}

void commitPathReservation(const CandidatePath& path,
                           double finishTime,
                           std::vector<std::vector<double>>& freeTime) {
    for (const auto& edge : pathToEdges(path)) {
        freeTime[edge.first][edge.second] = finishTime;
    }
}

std::vector<std::vector<int>> computeTorShortestHops(const std::vector<std::vector<double>>& capacity,
                                                     int numTor) {
    if (numTor <= 0) {
        throw std::runtime_error("numTor must be > 0 when computing shortest hops.");
    }

    std::vector<std::vector<int>> dist(numTor, std::vector<int>(numTor, -1));
    for (int src = 0; src < numTor; ++src) {
        std::queue<int> q;
        dist[src][src] = 0;
        q.push(src);

        while (!q.empty()) {
            const int u = q.front();
            q.pop();
            for (int v = 0; v < numTor; ++v) {
                if (capacity[u][v] <= 1e-9 || dist[src][v] != -1) {
                    continue;
                }
                dist[src][v] = dist[src][u] + 1;
                q.push(v);
            }
        }
    }
    return dist;
}

int computeDiameterFromShortestHops(const std::vector<std::vector<int>>& shortestHop) {
    const int numTor = static_cast<int>(shortestHop.size());
    int diameter = 0;
    for (int s = 0; s < numTor; ++s) {
        for (int t = 0; t < numTor; ++t) {
            const int d = shortestHop[s][t];
            if (d < 0) {
                throw std::runtime_error(
                    "ToR subgraph is disconnected; cannot compute finite diameter for pure_ocs_3hop_preset.");
            }
            diameter = std::max(diameter, d);
        }
    }
    return diameter;
}

}  // namespace

PureOcs3HopKspScheduler::PureOcs3HopKspScheduler(int kspK, int maxCandidates)
    : kspK_(kspK), maxCandidates_(maxCandidates) {
    if (kspK_ <= 0) {
        throw std::runtime_error("pure_ocs_3hop_preset requires kspK > 0.");
    }
    if (maxCandidates_ <= 0) {
        throw std::runtime_error("pure_ocs_3hop_preset requires maxCandidates > 0.");
    }
}

uint64_t PureOcs3HopKspScheduler::pairKey(int s, int t) {
    return (static_cast<uint64_t>(static_cast<uint32_t>(s)) << 32) |
           static_cast<uint32_t>(t);
}

void PureOcs3HopKspScheduler::prepare(const SchedulerContext& ctx) const {
    if (cachedCapacity_ == &ctx.capacity &&
        cachedNumTor_ == ctx.numTor &&
        cachedTorDiameter_ > 0 &&
        cachedEffectiveMaxHops_ > 0 &&
        !shortestHop_.empty() &&
        !cachedTemplateCandidates_.empty()) {
        return;
    }

    cachedCapacity_ = &ctx.capacity;
    cachedNumTor_ = ctx.numTor;
    shortestHop_ = computeTorShortestHops(ctx.capacity, ctx.numTor);
    cachedTorDiameter_ = computeDiameterFromShortestHops(shortestHop_);
    cachedEffectiveMaxHops_ = std::max(1, std::min(kMaxSearchedHops, cachedTorDiameter_));

    cachedTemplateCandidates_.assign(
        ctx.numTor, std::vector<std::vector<CandidatePath>>(ctx.numTor));
    for (int s = 0; s < ctx.numTor; ++s) {
        for (int t = 0; t < ctx.numTor; ++t) {
            if (s == t) {
                continue;
            }
            if (shortestHop_[s][t] <= kMaxSearchedHops) {
                cachedTemplateCandidates_[s][t] =
                    enumerateTemplateOcsPaths(
                        s, t, ctx.capacity, ctx.numTor, cachedEffectiveMaxHops_, maxCandidates_);
            }
        }
    }

    fallbackKspPath_.clear();
    fallbackKspPath_.reserve(static_cast<size_t>(ctx.numTor) * static_cast<size_t>(ctx.numTor));

    for (int s = 0; s < ctx.numTor; ++s) {
        for (int t = 0; t < ctx.numTor; ++t) {
            if (s == t) {
                continue;
            }
            const int d = shortestHop_[s][t];
            if (d <= kMaxSearchedHops) {
                continue;
            }
            auto ksp = enumerateKShortestPaths(s, t, ctx.capacity, kspK_, ctx.numTor);
            if (ksp.empty()) {
                throw std::runtime_error("No KSP fallback path found for pair (" +
                                         std::to_string(s) + "," + std::to_string(t) + ").");
            }
            fallbackKspPath_[pairKey(s, t)] = ksp.front();
        }
    }
}

std::string PureOcs3HopKspScheduler::name() const {
    return "pure_ocs_3hop_preset";
}

std::vector<ScheduledFlow> PureOcs3HopKspScheduler::scheduleJob(const Job& job,
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

        if (flow.torSrc < 0 || flow.torSrc >= ctx.numTor || flow.torDst < 0 || flow.torDst >= ctx.numTor) {
            throw std::runtime_error("Flow ToR id out of range in pure_ocs_3hop_preset.");
        }

        const int shortestHop = shortestHop_[flow.torSrc][flow.torDst];
        if (shortestHop < 0) {
            throw std::runtime_error("No ToR path found for flowId=" + std::to_string(flow.flowId));
        }

        std::vector<PathHeuristic> evalCandidates;
        if (shortestHop <= kMaxSearchedHops) {
            const auto& candidates = cachedTemplateCandidates_[flow.torSrc][flow.torDst];
            if (candidates.empty()) {
                throw std::runtime_error("No <=3-hop template candidate path found for flowId=" +
                                         std::to_string(flow.flowId));
            }
            evalCandidates = pruneCandidatesByType(candidates, ctx.capacity, localFreeTime, ctx.numTor);
        } else {
            const auto it = fallbackKspPath_.find(pairKey(flow.torSrc, flow.torDst));
            if (it == fallbackKspPath_.end()) {
                throw std::runtime_error("Missing KSP fallback path for flowId=" +
                                         std::to_string(flow.flowId));
            }
            evalCandidates.push_back(buildPathHeuristic(it->second, ctx.capacity, localFreeTime));
        }

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
