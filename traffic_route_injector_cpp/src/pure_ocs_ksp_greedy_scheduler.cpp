#include "pure_ocs_ksp_greedy_scheduler.h"

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

struct CandidateEval {
    const PureOcsKspGreedyScheduler::CachedCandidate* candidate = nullptr;
    double releaseTime = 0.0;
    double estimatedRate = 0.0;
    double estimatedFinishTime = 0.0;
};

int edgeId(int u, int v, int nodeCount) {
    return u * nodeCount + v;
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

std::vector<PureOcsKspGreedyScheduler::CachedCandidate> buildCachedCandidates(
    const std::vector<CandidatePath>& raw, int nodeCount) {
    std::vector<PureOcsKspGreedyScheduler::CachedCandidate> cached;
    cached.reserve(raw.size());
    for (const auto& path : raw) {
        PureOcsKspGreedyScheduler::CachedCandidate item;
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
                                const PureOcsKspGreedyScheduler::CachedCandidate& candidate,
                                const SchedulerContext& ctx,
                                const std::vector<double>& localEdgeFreeTime) {
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

    eval.estimatedFinishTime = eval.releaseTime + flow.bytes / eval.estimatedRate;
    return eval;
}

}  // namespace

PureOcsKspGreedyScheduler::PureOcsKspGreedyScheduler(int kspK) : kspK_(kspK) {
    if (kspK_ <= 0) {
        throw std::runtime_error("pure_ocs_ksp_greedy requires kspK > 0.");
    }
}

uint64_t PureOcsKspGreedyScheduler::pairKey(int s, int t) {
    return (static_cast<uint64_t>(static_cast<uint32_t>(s)) << 32) |
           static_cast<uint32_t>(t);
}

void PureOcsKspGreedyScheduler::prepare(const SchedulerContext& ctx) const {
    const int maxNodeExclusive = ctx.numTor;
    const int nodeCount = static_cast<int>(ctx.capacity.size());
    if (cachedCapacity_ == &ctx.capacity &&
        cachedNumTor_ == ctx.numTor &&
        cachedMaxNodeExclusive_ == maxNodeExclusive &&
        cachedNodeCount_ == nodeCount &&
        !shortestHop_.empty() &&
        !kspCache_.empty()) {
        return;
    }

    cachedCapacity_ = &ctx.capacity;
    cachedNumTor_ = ctx.numTor;
    cachedMaxNodeExclusive_ = maxNodeExclusive;
    cachedNodeCount_ = nodeCount;
    shortestHop_ = computeTorShortestHops(ctx.capacity, ctx.numTor);
    kspCache_.clear();
    kspCache_.reserve(static_cast<size_t>(maxNodeExclusive) * static_cast<size_t>(maxNodeExclusive));

    for (int s = 0; s < ctx.numTor; ++s) {
        for (int t = 0; t < ctx.numTor; ++t) {
            if (s == t) {
                continue;
            }
            auto rawCandidates = enumerateKShortestPaths(s, t, ctx.capacity, kspK_, maxNodeExclusive);
            kspCache_[pairKey(s, t)] = buildCachedCandidates(rawCandidates, nodeCount);
        }
    }
}

bool PureOcsKspGreedyScheduler::countsSolveTime() const {
    // Count online greedy path selection only (KSP precompute and transmission simulation excluded).
    return true;
}

double PureOcsKspGreedyScheduler::reportedSolveTimeMs(double measuredWallTimeMs) const {
    (void)measuredWallTimeMs;
    return lastGreedySolveTimeMs_;
}

std::string PureOcsKspGreedyScheduler::name() const {
    return "pure_ocs_ksp_greedy";
}

std::vector<ScheduledFlow> PureOcsKspGreedyScheduler::scheduleJob(const Job& job,
                                                                  const SchedulerContext& ctx) const {
    const int expectedMaxNodeExclusive = ctx.numTor;
    const int nodeCount = static_cast<int>(ctx.capacity.size());
    if (cachedCapacity_ != &ctx.capacity ||
        cachedNumTor_ != ctx.numTor ||
        cachedMaxNodeExclusive_ != expectedMaxNodeExclusive ||
        cachedNodeCount_ != nodeCount ||
        shortestHop_.empty() ||
        kspCache_.empty()) {
        throw std::runtime_error(
            "pure_ocs_ksp_greedy cache is not prepared. Call prepare(ctx) before scheduleJob().");
    }
    lastGreedySolveTimeMs_ = 0.0;

    std::vector<ScheduledFlow> scheduledImmediate;
    std::vector<ScheduledFlow> scheduledChosen;
    scheduledChosen.reserve(job.flows.size());
    std::vector<double> localEdgeFreeTime(static_cast<size_t>(nodeCount) * static_cast<size_t>(nodeCount), 0.0);
    for (int u = 0; u < nodeCount; ++u) {
        for (int v = 0; v < nodeCount; ++v) {
            localEdgeFreeTime[edgeId(u, v, nodeCount)] = ctx.currentFreeTime[u][v];
        }
    }

    // Sort inside scheduler so solve time includes sort + greedy decision.
    std::vector<const Flow*> flowOrder;
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
        flowOrder.push_back(&flow);
    }

    const auto greedyStart = std::chrono::high_resolution_clock::now();
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

    for (const Flow* flowPtr : flowOrder) {
        const Flow& flow = *flowPtr;
        const auto it = kspCache_.find(pairKey(flow.torSrc, flow.torDst));
        if (it == kspCache_.end() || it->second.empty()) {
            throw std::runtime_error("No pure OCS-KSP candidate path found for flowId=" +
                                     std::to_string(flow.flowId));
        }

        bool chosen = false;
        CandidateEval best;
        for (const auto& candidate : it->second) {
            const auto cand = evaluateCandidate(flow, candidate, ctx, localEdgeFreeTime);
            if (!chosen ||
                cand.estimatedFinishTime < best.estimatedFinishTime - 1e-12 ||
                (std::fabs(cand.estimatedFinishTime - best.estimatedFinishTime) <= 1e-12 &&
                 cand.releaseTime < best.releaseTime - 1e-12) ||
                (std::fabs(cand.estimatedFinishTime - best.estimatedFinishTime) <= 1e-12 &&
                 std::fabs(cand.releaseTime - best.releaseTime) <= 1e-12 &&
                 cand.estimatedRate > best.estimatedRate + 1e-12) ||
                (std::fabs(cand.estimatedFinishTime - best.estimatedFinishTime) <= 1e-12 &&
                 std::fabs(cand.releaseTime - best.releaseTime) <= 1e-12 &&
                 std::fabs(cand.estimatedRate - best.estimatedRate) <= 1e-12 &&
                 cand.candidate->path.nodes.size() < best.candidate->path.nodes.size())) {
                chosen = true;
                best = cand;
            }
        }
        if (!chosen) {
            throw std::runtime_error("Failed to choose greedy KSP path for flowId=" +
                                     std::to_string(flow.flowId));
        }

        for (const int eid : best.candidate->edgeIds) {
            localEdgeFreeTime[eid] = best.estimatedFinishTime;
        }

        ScheduledFlow sf;
        sf.flow = flow;
        sf.corePath = best.candidate->path.nodes;
        sf.sameTorBypass = false;
        sf.serviceStartTime = best.releaseTime;
        sf.finishTime = best.estimatedFinishTime;
        sf.bottleneckRate = best.estimatedRate;
        scheduledChosen.push_back(std::move(sf));
    }
    const auto greedyEnd = std::chrono::high_resolution_clock::now();
    lastGreedySolveTimeMs_ =
        std::chrono::duration<double, std::milli>(greedyEnd - greedyStart).count();

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
