#include "ocs_eps_preset_greedy_scheduler.h"

#include <chrono>
#include <algorithm>
#include <cmath>
#include <limits>
#include <queue>
#include <stdexcept>
#include <tuple>
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

struct PendingFlow {
    const Flow* flow = nullptr;
    int shortestHop = -1;
    bool useEpsTemplate = false;
};

struct CandidateEval {
    const OcsEpsPresetGreedyScheduler::CachedCandidate* candidate = nullptr;
    double releaseTime = 0.0;
    double estimatedRate = 0.0;
    double estimatedFinishTime = 0.0;
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

std::vector<OcsEpsPresetGreedyScheduler::CachedCandidate> buildCachedCandidates(
    const std::vector<CandidatePath>& raw, int nodeCount) {
    std::vector<OcsEpsPresetGreedyScheduler::CachedCandidate> cached;
    cached.reserve(raw.size());
    for (const auto& path : raw) {
        OcsEpsPresetGreedyScheduler::CachedCandidate item;
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
                                const OcsEpsPresetGreedyScheduler::CachedCandidate& candidate,
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

OcsEpsPresetGreedyScheduler::OcsEpsPresetGreedyScheduler(int kspK, double epsTailPercent, int maxCandidates)
    : kspK_(kspK),
      epsTailPercent_(epsTailPercent),
      maxCandidates_(maxCandidates) {
    if (kspK_ <= 0) {
        throw std::runtime_error("ocs_eps_preset_greedy requires kspK > 0.");
    }
    if (epsTailPercent_ < 0.0 || epsTailPercent_ > 100.0) {
        throw std::runtime_error("ocs_eps_preset_greedy requires epsTailPercent in [0, 100].");
    }
    if (maxCandidates_ <= 0) {
        throw std::runtime_error("ocs_eps_preset_greedy requires maxCandidates > 0.");
    }
}

uint64_t OcsEpsPresetGreedyScheduler::pairKey(int s, int t) {
    return (static_cast<uint64_t>(static_cast<uint32_t>(s)) << 32) |
           static_cast<uint32_t>(t);
}

void OcsEpsPresetGreedyScheduler::prepare(const SchedulerContext& ctx) const {
    const int nodeCount = static_cast<int>(ctx.capacity.size());
    if (cachedCapacity_ == &ctx.capacity &&
        cachedNumTor_ == ctx.numTor &&
        cachedNumEps_ == ctx.numEps &&
        cachedNodeCount_ == nodeCount &&
        !shortestHop_.empty() &&
        !kspCache_.empty() &&
        !epsTemplateCache_.empty()) {
        return;
    }

    cachedCapacity_ = &ctx.capacity;
    cachedNumTor_ = ctx.numTor;
    cachedNumEps_ = ctx.numEps;
    cachedNodeCount_ = nodeCount;

    shortestHop_ = computeTorShortestHops(ctx.capacity, ctx.numTor);
    kspCache_.clear();
    epsTemplateCache_.clear();
    kspCache_.reserve(static_cast<size_t>(ctx.numTor) * static_cast<size_t>(ctx.numTor));
    epsTemplateCache_.reserve(static_cast<size_t>(ctx.numTor) * static_cast<size_t>(ctx.numTor));

    for (int s = 0; s < ctx.numTor; ++s) {
        for (int t = 0; t < ctx.numTor; ++t) {
            if (s == t) {
                continue;
            }
            auto kspRaw = enumerateKShortestPaths(s, t, ctx.capacity, kspK_, ctx.numTor);
            auto epsRaw = enumerateEpsTemplatePaths(s, t, ctx.capacity, ctx.numTor, ctx.numEps, maxCandidates_);
            kspCache_[pairKey(s, t)] = buildCachedCandidates(kspRaw, nodeCount);
            epsTemplateCache_[pairKey(s, t)] = buildCachedCandidates(epsRaw, nodeCount);
        }
    }
}

std::string OcsEpsPresetGreedyScheduler::name() const {
    return "ocs_eps_preset_greedy";
}

double OcsEpsPresetGreedyScheduler::reportedSolveTimeMs(double measuredWallTimeMs) const {
    (void)measuredWallTimeMs;
    return lastSortGreedySolveTimeMs_;
}

std::vector<ScheduledFlow> OcsEpsPresetGreedyScheduler::scheduleJob(const Job& job,
                                                                    const SchedulerContext& ctx) const {
    const int nodeCount = static_cast<int>(ctx.capacity.size());
    if (cachedCapacity_ != &ctx.capacity ||
        cachedNumTor_ != ctx.numTor ||
        cachedNumEps_ != ctx.numEps ||
        cachedNodeCount_ != nodeCount ||
        shortestHop_.empty() ||
        kspCache_.empty() ||
        epsTemplateCache_.empty()) {
        throw std::runtime_error(
            "ocs_eps_preset_greedy cache is not prepared. Call prepare(ctx) before scheduleJob().");
    }
    lastSortGreedySolveTimeMs_ = 0.0;

    std::vector<ScheduledFlow> scheduledImmediate;
    std::vector<PendingFlow> pending;
    std::vector<ScheduledFlow> scheduledChosen;
    scheduledImmediate.reserve(job.flows.size());
    pending.reserve(job.flows.size());
    scheduledChosen.reserve(job.flows.size());

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
            throw std::runtime_error("Flow ToR id out of range in ocs_eps_preset_greedy.");
        }

        const int hop = shortestHop_[flow.torSrc][flow.torDst];
        PendingFlow pf;
        pf.flow = &flow;
        pf.shortestHop = hop;
        pending.push_back(pf);
    }

    // Keep coflow-level decision semantics:
    // - split flows by jobId (coflow)
    // - within each coflow, rank by hop/bytes and apply EPS-tail percent
    std::unordered_map<int, std::vector<PendingFlow>> pendingByJob;
    pendingByJob.reserve(job.flows.size());
    std::unordered_map<int, double> jobStart;
    jobStart.reserve(job.flows.size());
    for (const auto& item : pending) {
        pendingByJob[item.flow->jobId].push_back(item);
        auto it = jobStart.find(item.flow->jobId);
        if (it == jobStart.end()) {
            jobStart[item.flow->jobId] = item.flow->startTime;
        } else {
            it->second = std::min(it->second, item.flow->startTime);
        }
    }

    std::vector<int> jobOrder;
    jobOrder.reserve(pendingByJob.size());
    for (const auto& kv : pendingByJob) {
        jobOrder.push_back(kv.first);
    }

    std::vector<double> localEdgeFreeTime(static_cast<size_t>(nodeCount) * static_cast<size_t>(nodeCount), 0.0);
    for (int u = 0; u < nodeCount; ++u) {
        for (int v = 0; v < nodeCount; ++v) {
            localEdgeFreeTime[edgeId(u, v, nodeCount)] = ctx.currentFreeTime[u][v];
        }
    }

    const auto selectStart = std::chrono::high_resolution_clock::now();
    std::sort(jobOrder.begin(), jobOrder.end(), [&](int a, int b) {
        if (jobStart[a] != jobStart[b]) {
            return jobStart[a] < jobStart[b];
        }
        return a < b;
    });

    for (const int jid : jobOrder) {
        auto& group = pendingByJob[jid];

        // Stage 1/2 ranking for EPS subset selection INSIDE each coflow:
        // 1) shortest-hop ascending (larger hops appear later)
        // 2) within same hop, flow bytes ascending (larger flows appear later)
        std::sort(group.begin(), group.end(), [](const PendingFlow& a, const PendingFlow& b) {
            if (a.shortestHop != b.shortestHop) {
                if (a.shortestHop < 0) {
                    return false;  // Treat unreachable as the largest hop bucket.
                }
                if (b.shortestHop < 0) {
                    return true;
                }
                return a.shortestHop < b.shortestHop;
            }
            if (a.flow->bytes != b.flow->bytes) {
                return a.flow->bytes < b.flow->bytes;
            }
            if (a.flow->startTime != b.flow->startTime) {
                return a.flow->startTime < b.flow->startTime;
            }
            return a.flow->flowId < b.flow->flowId;
        });

        // EPS subset target is byte-based (not flow-count based):
        // mark from the sorted tail until EPS bytes reach epsTailPercent_.
        double totalBytes = 0.0;
        for (const auto& item : group) {
            totalBytes += item.flow->bytes;
        }
        const double epsTargetBytes = totalBytes * (epsTailPercent_ / 100.0);
        double epsAccumBytes = 0.0;
        if (epsTargetBytes > 0.0) {
            for (auto it = group.rbegin(); it != group.rend(); ++it) {
                if (epsAccumBytes >= epsTargetBytes - 1e-12) {
                    break;
                }
                it->useEpsTemplate = true;
                epsAccumBytes += it->flow->bytes;
            }
        }

        std::vector<const PendingFlow*> greedyOrder;
        greedyOrder.reserve(group.size());
        for (const auto& item : group) {
            greedyOrder.push_back(&item);
        }
        // Greedy traversal order:
        // prioritize larger shortest-hop first, and for same hop prioritize larger flow.
        std::sort(greedyOrder.begin(), greedyOrder.end(), [](const PendingFlow* a, const PendingFlow* b) {
            if (a->shortestHop != b->shortestHop) {
                if (a->shortestHop < 0) {
                    return true;   // Keep unreachable at the very front.
                }
                if (b->shortestHop < 0) {
                    return false;
                }
                return a->shortestHop > b->shortestHop;
            }
            if (a->flow->bytes != b->flow->bytes) {
                return a->flow->bytes > b->flow->bytes;
            }
            if (a->flow->startTime != b->flow->startTime) {
                return a->flow->startTime < b->flow->startTime;
            }
            return a->flow->flowId < b->flow->flowId;
        });

        for (const PendingFlow* itemPtr : greedyOrder) {
            const PendingFlow& item = *itemPtr;
            const Flow& flow = *item.flow;
            const uint64_t key = pairKey(flow.torSrc, flow.torDst);

            const std::vector<OcsEpsPresetGreedyScheduler::CachedCandidate>* candidates = nullptr;
            if (item.useEpsTemplate) {
                const auto it = epsTemplateCache_.find(key);
                if (it != epsTemplateCache_.end() && !it->second.empty()) {
                    candidates = &it->second;
                }
            } else {
                const auto it = kspCache_.find(key);
                if (it != kspCache_.end() && !it->second.empty()) {
                    candidates = &it->second;
                }
            }
            if (candidates == nullptr || candidates->empty()) {
                if (item.useEpsTemplate) {
                    const auto it = kspCache_.find(key);
                    if (it != kspCache_.end() && !it->second.empty()) {
                        candidates = &it->second;
                    }
                } else {
                    const auto it = epsTemplateCache_.find(key);
                    if (it != epsTemplateCache_.end() && !it->second.empty()) {
                        candidates = &it->second;
                    }
                }
            }
            if (candidates == nullptr || candidates->empty()) {
                throw std::runtime_error("No candidate path found in ocs_eps_preset_greedy for flowId=" +
                                         std::to_string(flow.flowId));
            }

            bool chosen = false;
            CandidateEval best;
            const int candLimit = std::min(maxCandidates_, static_cast<int>(candidates->size()));
            for (int i = 0; i < candLimit; ++i) {
                const auto cand = evaluateCandidate(flow, (*candidates)[i], ctx, localEdgeFreeTime);
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
                throw std::runtime_error("Failed to choose path in ocs_eps_preset_greedy for flowId=" +
                                         std::to_string(flow.flowId));
            }

            for (const int eid : best.candidate->edgeIds) {
                localEdgeFreeTime[eid] = best.estimatedFinishTime;
            }

            ScheduledFlow sf;
            sf.flow = flow;
            sf.sameTorBypass = false;
            sf.corePath = best.candidate->path.nodes;
            sf.serviceStartTime = best.releaseTime;
            sf.finishTime = best.estimatedFinishTime;
            sf.bottleneckRate = best.estimatedRate;
            scheduledChosen.push_back(std::move(sf));
        }
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
