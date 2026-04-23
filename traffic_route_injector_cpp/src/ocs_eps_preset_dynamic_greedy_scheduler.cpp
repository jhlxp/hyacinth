#include "ocs_eps_preset_dynamic_greedy_scheduler.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <queue>
#include <stdexcept>
#include <unordered_map>
#include <vector>

#include "path_utils.h"

namespace flsim {
namespace {

enum class PathType {
    TorTor = 0,
    TorTorTor = 1,
    TorTorTorTor = 2,
    TorEpsTor = 3,
    TorTorEpsTor = 4,
    TorEpsTorTor = 5,
    Unknown = 6,
};

struct CandidateEval {
    const OcsEpsPresetDynamicGreedyScheduler::CachedCandidate* candidate = nullptr;
    double releaseTime = 0.0;
    double estimatedRate = 0.0;
    double estimatedFinishTime = 0.0;
    double duration = 0.0;
    double projectedWorstLinkLoad = 0.0;
};

int edgeId(int u, int v, int nodeCount) {
    return u * nodeCount + v;
}

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

bool isEpsTemplatePath(PathType type) {
    return type == PathType::TorEpsTor ||
           type == PathType::TorEpsTorTor ||
           type == PathType::TorTorEpsTor;
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

std::vector<CandidatePath> enumerateEpsTemplatePaths(int s,
                                                     int t,
                                                     const std::vector<std::vector<double>>& capacity,
                                                     int numTor,
                                                     int numEps,
                                                     int maxCandidates) {
    auto raw = enumerateCandidatePaths(s, t, capacity, numTor, numEps);

    std::vector<CandidatePath> filtered;
    filtered.reserve(raw.size());
    for (const auto& path : raw) {
        if (!isEpsTemplatePath(inferPathType(path, numTor))) {
            continue;
        }
        filtered.push_back(path);
    }

    std::sort(filtered.begin(), filtered.end(), [](const CandidatePath& a, const CandidatePath& b) {
        if (a.nodes.size() != b.nodes.size()) {
            return a.nodes.size() < b.nodes.size();
        }
        return a.nodes < b.nodes;
    });
    if (maxCandidates > 0 && static_cast<int>(filtered.size()) > maxCandidates) {
        filtered.resize(maxCandidates);
    }
    return filtered;
}

std::vector<OcsEpsPresetDynamicGreedyScheduler::CachedCandidate> buildCachedCandidates(
    const std::vector<CandidatePath>& raw, int nodeCount) {
    std::vector<OcsEpsPresetDynamicGreedyScheduler::CachedCandidate> cached;
    cached.reserve(raw.size());
    for (const auto& path : raw) {
        OcsEpsPresetDynamicGreedyScheduler::CachedCandidate item;
        item.path = path;
        item.edges = pathToEdges(path);
        item.edgeIds.reserve(item.edges.size());
        for (const auto& edge : item.edges) {
            item.edgeIds.push_back(edgeId(edge.first, edge.second, nodeCount));
        }
        cached.push_back(std::move(item));
    }
    return cached;
}

CandidateEval evaluateCandidate(const Flow& flow,
                                const OcsEpsPresetDynamicGreedyScheduler::CachedCandidate& candidate,
                                const SchedulerContext& ctx,
                                const std::vector<double>& localEdgeFreeTime,
                                const std::vector<double>& currentEdgeLoad,
                                double currentWorstEdgeLoad) {
    CandidateEval eval;
    eval.candidate = &candidate;
    eval.releaseTime = flow.startTime;
    eval.estimatedRate = std::numeric_limits<double>::infinity();

    for (size_t i = 0; i < candidate.edges.size(); ++i) {
        const int u = candidate.edges[i].first;
        const int v = candidate.edges[i].second;
        const double cap = ctx.capacity[u][v];
        if (cap <= 0.0) {
            throw std::runtime_error("Candidate path contains an edge with non-positive capacity.");
        }
        eval.releaseTime = std::max(eval.releaseTime, localEdgeFreeTime[candidate.edgeIds[i]]);
        eval.estimatedRate = std::min(eval.estimatedRate, cap);
    }

    eval.duration = flow.bytes / eval.estimatedRate;
    eval.estimatedFinishTime = eval.releaseTime + eval.duration;
    eval.projectedWorstLinkLoad = currentWorstEdgeLoad;
    for (const int eid : candidate.edgeIds) {
        const double projectedLoad = currentEdgeLoad[eid] + eval.duration;
        eval.projectedWorstLinkLoad = std::max(eval.projectedWorstLinkLoad, projectedLoad);
    }
    return eval;
}

bool betterEval(const CandidateEval& a, const CandidateEval& b) {
    // Pure min-max greedy: prioritize smaller projected worst-link load.
    if (a.projectedWorstLinkLoad < b.projectedWorstLinkLoad - 1e-12) {
        return true;
    }
    if (std::fabs(a.projectedWorstLinkLoad - b.projectedWorstLinkLoad) > 1e-12) {
        return false;
    }
    if (a.estimatedFinishTime < b.estimatedFinishTime - 1e-12) {
        return true;
    }
    if (std::fabs(a.estimatedFinishTime - b.estimatedFinishTime) > 1e-12) {
        return false;
    }
    if (a.releaseTime < b.releaseTime - 1e-12) {
        return true;
    }
    if (std::fabs(a.releaseTime - b.releaseTime) > 1e-12) {
        return false;
    }
    if (a.estimatedRate > b.estimatedRate + 1e-12) {
        return true;
    }
    if (std::fabs(a.estimatedRate - b.estimatedRate) > 1e-12) {
        return false;
    }
    return a.candidate->path.nodes.size() < b.candidate->path.nodes.size();
}

}  // namespace

OcsEpsPresetDynamicGreedyScheduler::OcsEpsPresetDynamicGreedyScheduler(
    int kspK,
    int maxCandidates)
    : kspK_(kspK),
      maxCandidates_(maxCandidates) {
    if (kspK_ <= 0) {
        throw std::runtime_error("ocs_eps_preset_dynamic_greedy requires kspK > 0.");
    }
    if (maxCandidates_ <= 0) {
        throw std::runtime_error("ocs_eps_preset_dynamic_greedy requires maxCandidates > 0.");
    }
}

uint64_t OcsEpsPresetDynamicGreedyScheduler::pairKey(int s, int t) {
    return (static_cast<uint64_t>(static_cast<uint32_t>(s)) << 32) |
           static_cast<uint32_t>(t);
}

void OcsEpsPresetDynamicGreedyScheduler::prepare(const SchedulerContext& ctx) const {
    const int nodeCount = static_cast<int>(ctx.capacity.size());
    if (cachedCapacity_ == &ctx.capacity &&
        cachedNumTor_ == ctx.numTor &&
        cachedNumEps_ == ctx.numEps &&
        cachedNodeCount_ == nodeCount &&
        !shortestHop_.empty() &&
        !ocsCache_.empty() &&
        !epsTemplateCache_.empty()) {
        return;
    }

    cachedCapacity_ = &ctx.capacity;
    cachedNumTor_ = ctx.numTor;
    cachedNumEps_ = ctx.numEps;
    cachedNodeCount_ = nodeCount;
    shortestHop_ = computeTorShortestHops(ctx.capacity, ctx.numTor);

    ocsCache_.clear();
    epsTemplateCache_.clear();
    ocsCache_.reserve(static_cast<size_t>(ctx.numTor) * static_cast<size_t>(ctx.numTor));
    epsTemplateCache_.reserve(static_cast<size_t>(ctx.numTor) * static_cast<size_t>(ctx.numTor));

    for (int s = 0; s < ctx.numTor; ++s) {
        for (int t = 0; t < ctx.numTor; ++t) {
            if (s == t) {
                continue;
            }
            auto ocsRaw = enumerateKShortestPaths(s, t, ctx.capacity, kspK_, ctx.numTor);
            auto epsRaw = enumerateEpsTemplatePaths(s, t, ctx.capacity, ctx.numTor, ctx.numEps, maxCandidates_);
            ocsCache_[pairKey(s, t)] = buildCachedCandidates(ocsRaw, nodeCount);
            epsTemplateCache_[pairKey(s, t)] = buildCachedCandidates(epsRaw, nodeCount);
        }
    }
}

std::string OcsEpsPresetDynamicGreedyScheduler::name() const {
    return "ocs_eps_preset_dynamic_greedy";
}

double OcsEpsPresetDynamicGreedyScheduler::reportedSolveTimeMs(double measuredWallTimeMs) const {
    (void)measuredWallTimeMs;
    return lastSortGreedySolveTimeMs_;
}

std::vector<ScheduledFlow> OcsEpsPresetDynamicGreedyScheduler::scheduleJob(const Job& job,
                                                                            const SchedulerContext& ctx) const {
    const int nodeCount = static_cast<int>(ctx.capacity.size());
    if (cachedCapacity_ != &ctx.capacity ||
        cachedNumTor_ != ctx.numTor ||
        cachedNumEps_ != ctx.numEps ||
        cachedNodeCount_ != nodeCount ||
        shortestHop_.empty() ||
        ocsCache_.empty() ||
        epsTemplateCache_.empty()) {
        throw std::runtime_error(
            "ocs_eps_preset_dynamic_greedy cache is not prepared. Call prepare(ctx) before scheduleJob().");
    }

    lastSortGreedySolveTimeMs_ = 0.0;

    std::vector<ScheduledFlow> scheduledImmediate;
    std::vector<ScheduledFlow> scheduledChosen;
    std::vector<const Flow*> flowOrder;
    scheduledImmediate.reserve(job.flows.size());
    scheduledChosen.reserve(job.flows.size());
    flowOrder.reserve(job.flows.size());

    for (const auto& flow : job.flows) {
        if (flow.torSrc == flow.torDst) {
            ScheduledFlow sf;
            sf.flow = flow;
            sf.sameTorBypass = true;
            sf.corePath = {flow.torSrc};
            sf.serviceStartTime = flow.startTime;
            sf.finishTime = flow.startTime;
            sf.bottleneckRate = std::numeric_limits<double>::infinity();
            scheduledImmediate.push_back(sf);
            continue;
        }

        if (flow.torSrc < 0 || flow.torSrc >= ctx.numTor || flow.torDst < 0 || flow.torDst >= ctx.numTor) {
            throw std::runtime_error("Flow ToR id out of range in ocs_eps_preset_dynamic_greedy.");
        }

        flowOrder.push_back(&flow);
    }

    std::vector<double> localEdgeFreeTime(static_cast<size_t>(nodeCount) * static_cast<size_t>(nodeCount), 0.0);
    for (int u = 0; u < nodeCount; ++u) {
        for (int v = 0; v < nodeCount; ++v) {
            localEdgeFreeTime[edgeId(u, v, nodeCount)] = ctx.currentFreeTime[u][v];
        }
    }
    std::vector<double> localEdgeLoad(static_cast<size_t>(nodeCount) * static_cast<size_t>(nodeCount), 0.0);
    double currentWorstEdgeLoad = 0.0;

    const auto selectStart = std::chrono::high_resolution_clock::now();

    // Keep the same greedy ordering semantics as preset_greedy:
    // rank by hop asc + bytes asc, then consume from tail (equivalently sort desc for traversal).
    std::sort(flowOrder.begin(), flowOrder.end(), [this](const Flow* a, const Flow* b) {
        int hopA = -1;
        int hopB = -1;
        if (a->torSrc >= 0 && a->torSrc < static_cast<int>(shortestHop_.size()) &&
            a->torDst >= 0 && a->torDst < static_cast<int>(shortestHop_[a->torSrc].size())) {
            hopA = shortestHop_[a->torSrc][a->torDst];
        }
        if (b->torSrc >= 0 && b->torSrc < static_cast<int>(shortestHop_.size()) &&
            b->torDst >= 0 && b->torDst < static_cast<int>(shortestHop_[b->torSrc].size())) {
            hopB = shortestHop_[b->torSrc][b->torDst];
        }
        if (hopA != hopB) {
            if (hopA < 0) {
                return true;   // Keep unreachable at the very front.
            }
            if (hopB < 0) {
                return false;
            }
            return hopA > hopB;
        }
        if (a->bytes != b->bytes) {
            return a->bytes > b->bytes;
        }
        if (a->startTime != b->startTime) {
            return a->startTime < b->startTime;
        }
        return a->flowId < b->flowId;
    });

    auto selectBestFromMergedPool = [&](const Flow& flow, CandidateEval& out) -> bool {
        const uint64_t key = pairKey(flow.torSrc, flow.torDst);

        const std::vector<CachedCandidate>* ocsCandidates = nullptr;
        const std::vector<CachedCandidate>* epsCandidates = nullptr;

        const auto ocsIt = ocsCache_.find(key);
        if (ocsIt != ocsCache_.end() && !ocsIt->second.empty()) {
            ocsCandidates = &ocsIt->second;
        }
        const auto epsIt = epsTemplateCache_.find(key);
        if (epsIt != epsTemplateCache_.end() && !epsIt->second.empty()) {
            epsCandidates = &epsIt->second;
        }

        bool hasBest = false;
        CandidateEval best;

        auto relaxPool = [&](const std::vector<CachedCandidate>* pool) {
            if (pool == nullptr || pool->empty()) {
                return;
            }
            const int candLimit = std::min(maxCandidates_, static_cast<int>(pool->size()));
            for (int i = 0; i < candLimit; ++i) {
                const auto cand =
                    evaluateCandidate(flow,
                                      (*pool)[i],
                                      ctx,
                                      localEdgeFreeTime,
                                      localEdgeLoad,
                                      currentWorstEdgeLoad);
                if (!hasBest || betterEval(cand, best)) {
                    hasBest = true;
                    best = cand;
                }
            }
        };
        relaxPool(ocsCandidates);
        relaxPool(epsCandidates);

        if (!hasBest) {
            return false;
        }

        out = best;
        return true;
    };

    auto commitChosen = [&](const Flow& flow, const CandidateEval& chosen) {
        for (const int eid : chosen.candidate->edgeIds) {
            localEdgeFreeTime[eid] = chosen.estimatedFinishTime;
            localEdgeLoad[eid] += chosen.duration;
            currentWorstEdgeLoad = std::max(currentWorstEdgeLoad, localEdgeLoad[eid]);
        }

        ScheduledFlow sf;
        sf.flow = flow;
        sf.sameTorBypass = false;
        sf.corePath = chosen.candidate->path.nodes;
        sf.serviceStartTime = chosen.releaseTime;
        sf.finishTime = chosen.estimatedFinishTime;
        sf.bottleneckRate = chosen.estimatedRate;
        scheduledChosen.push_back(std::move(sf));
    };

    for (const Flow* flowPtr : flowOrder) {
        const Flow& flow = *flowPtr;
        CandidateEval chosenEval;
        if (!selectBestFromMergedPool(flow, chosenEval)) {
            throw std::runtime_error("No candidate path found in ocs_eps_preset_dynamic_greedy for flowId=" +
                                     std::to_string(flow.flowId));
        }
        commitChosen(flow, chosenEval);
    }

    const auto selectEnd = std::chrono::high_resolution_clock::now();
    lastSortGreedySolveTimeMs_ =
        std::chrono::duration<double, std::milli>(selectEnd - selectStart).count();

    std::vector<ScheduledFlow> scheduled;
    scheduled.reserve(scheduledImmediate.size() + scheduledChosen.size());
    for (const auto& sf : scheduledImmediate) {
        scheduled.push_back(sf);
    }
    for (const auto& sf : scheduledChosen) {
        scheduled.push_back(sf);
    }

    return scheduled;
}

}  // namespace flsim
