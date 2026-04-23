#include "ocs_eps_global_ksp_scheduler.h"

#include <cstdint>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <unordered_map>
#include <vector>

#include "path_utils.h"

namespace flsim {
namespace {

uint64_t mix64(uint64_t x) {
    x ^= (x >> 30);
    x *= 0xbf58476d1ce4e5b9ULL;
    x ^= (x >> 27);
    x *= 0x94d049bb133111ebULL;
    x ^= (x >> 31);
    return x;
}

size_t pickCandidateIndex(const Flow& flow, size_t candidateCount) {
    if (candidateCount == 0) {
        return 0;
    }
    uint64_t key = 0xcbf29ce484222325ULL;
    key ^= static_cast<uint64_t>(flow.jobId + 0x9e3779b9);
    key = mix64(key);
    key ^= static_cast<uint64_t>(flow.flowId + 0x9e3779b9);
    key = mix64(key);
    key ^= static_cast<uint64_t>(flow.aggSrc + 0x9e3779b9);
    key = mix64(key);
    key ^= static_cast<uint64_t>(flow.aggDst + 0x9e3779b9);
    key = mix64(key);
    return static_cast<size_t>(key % static_cast<uint64_t>(candidateCount));
}

uint64_t edgeKey(int u, int v) {
    return (static_cast<uint64_t>(static_cast<uint32_t>(u)) << 32) |
           static_cast<uint32_t>(v);
}

struct PlannedFlow {
    Flow flow;
    CandidatePath path;
    std::vector<Edge> edges;
    double releaseTime = 0.0;
    double remainingBytes = 0.0;
    bool started = false;
    bool finished = false;
    double serviceStartTime = 0.0;
    double finishTime = 0.0;
    double initialRate = 0.0;
};

}  // namespace

OcsEpsGlobalKspScheduler::OcsEpsGlobalKspScheduler(int kspK) : kspK_(kspK) {
    if (kspK_ <= 0) {
        throw std::runtime_error("ocs_eps_global_ksp requires kspK > 0.");
    }
}

uint64_t OcsEpsGlobalKspScheduler::pairKey(int s, int t) {
    return (static_cast<uint64_t>(static_cast<uint32_t>(s)) << 32) |
           static_cast<uint32_t>(t);
}

void OcsEpsGlobalKspScheduler::prepare(const SchedulerContext& ctx) const {
    const int maxNodeExclusive = ctx.numTor + ctx.numEps;
    if (cachedCapacity_ == &ctx.capacity &&
        cachedMaxNodeExclusive_ == maxNodeExclusive &&
        !kspCache_.empty()) {
        return;
    }

    cachedCapacity_ = &ctx.capacity;
    cachedMaxNodeExclusive_ = maxNodeExclusive;
    kspCache_.clear();
    kspCache_.reserve(static_cast<size_t>(ctx.numTor) * static_cast<size_t>(ctx.numTor));

    for (int s = 0; s < ctx.numTor; ++s) {
        for (int t = 0; t < ctx.numTor; ++t) {
            if (s == t) {
                continue;
            }
            auto candidates = enumerateKShortestPaths(s, t, ctx.capacity, kspK_, maxNodeExclusive);
            kspCache_[pairKey(s, t)] = std::move(candidates);
        }
    }
}

bool OcsEpsGlobalKspScheduler::countsSolveTime() const {
    // KSP routes are treated as precomputed/offline.
    return false;
}

std::string OcsEpsGlobalKspScheduler::name() const {
    return "ocs_eps_global_ksp";
}

std::vector<ScheduledFlow> OcsEpsGlobalKspScheduler::scheduleJob(const Job& job,
                                                                 const SchedulerContext& ctx) const {
    prepare(ctx);

    std::vector<ScheduledFlow> scheduledImmediate;
    std::vector<PlannedFlow> planned;
    planned.reserve(job.flows.size());

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

        const auto it = kspCache_.find(pairKey(flow.torSrc, flow.torDst));
        if (it == kspCache_.end() || it->second.empty()) {
            throw std::runtime_error("No OCS-EPS global KSP candidate path found for flowId=" +
                                     std::to_string(flow.flowId));
        }
        const auto& candidates = it->second;

        PlannedFlow pf;
        pf.flow = flow;
        pf.path = candidates[pickCandidateIndex(flow, candidates.size())];
        pf.edges = pathToEdges(pf.path);
        pf.remainingBytes = flow.bytes;
        pf.releaseTime = flow.startTime;

        for (const auto& edge : pf.edges) {
            const int u = edge.first;
            const int v = edge.second;
            if (ctx.capacity[u][v] <= 0.0) {
                throw std::runtime_error("Candidate path contains an edge with non-positive capacity.");
            }
            pf.releaseTime = std::max(pf.releaseTime, ctx.currentFreeTime[u][v]);
        }
        planned.push_back(std::move(pf));
    }

    const double kEps = 1e-12;
    int done = 0;
    double now = std::numeric_limits<double>::infinity();
    for (const auto& pf : planned) {
        if (pf.releaseTime < now) {
            now = pf.releaseTime;
        }
    }
    if (!std::isfinite(now)) {
        now = 0.0;
    }

    while (done < static_cast<int>(planned.size())) {
        for (auto& pf : planned) {
            if (!pf.finished && pf.remainingBytes <= kEps) {
                pf.finished = true;
                pf.finishTime = now;
                ++done;
            }
        }
        if (done >= static_cast<int>(planned.size())) {
            break;
        }

        std::vector<int> active;
        active.reserve(planned.size());
        for (int i = 0; i < static_cast<int>(planned.size()); ++i) {
            auto& pf = planned[i];
            if (!pf.finished && pf.releaseTime <= now + kEps) {
                if (!pf.started) {
                    pf.started = true;
                    pf.serviceStartTime = now;
                }
                active.push_back(i);
            }
        }

        if (active.empty()) {
            double nextRelease = std::numeric_limits<double>::infinity();
            for (const auto& pf : planned) {
                if (!pf.finished && pf.releaseTime > now + kEps) {
                    nextRelease = std::min(nextRelease, pf.releaseTime);
                }
            }
            if (!std::isfinite(nextRelease)) {
                throw std::runtime_error("No active global KSP flow and no future release; invalid state.");
            }
            now = nextRelease;
            continue;
        }

        std::unordered_map<uint64_t, int> edgeActiveCount;
        edgeActiveCount.reserve(active.size() * 4);
        for (int idx : active) {
            for (const auto& edge : planned[idx].edges) {
                ++edgeActiveCount[edgeKey(edge.first, edge.second)];
            }
        }

        std::vector<double> rates(planned.size(), 0.0);
        double nextFinishDt = std::numeric_limits<double>::infinity();
        for (int idx : active) {
            auto& pf = planned[idx];
            double rate = std::numeric_limits<double>::infinity();
            for (const auto& edge : pf.edges) {
                const double cap = ctx.capacity[edge.first][edge.second];
                const auto it = edgeActiveCount.find(edgeKey(edge.first, edge.second));
                if (it == edgeActiveCount.end() || it->second <= 0) {
                    throw std::runtime_error("Global KSP share accounting failed for an active edge.");
                }
                rate = std::min(rate, cap / static_cast<double>(it->second));
            }
            if (!(rate > 0.0)) {
                throw std::runtime_error("Global KSP shared rate must be positive.");
            }
            if (pf.initialRate <= 0.0) {
                pf.initialRate = rate;
            }
            rates[idx] = rate;
            nextFinishDt = std::min(nextFinishDt, pf.remainingBytes / rate);
        }

        double nextReleaseDt = std::numeric_limits<double>::infinity();
        for (const auto& pf : planned) {
            if (!pf.finished && pf.releaseTime > now + kEps) {
                nextReleaseDt = std::min(nextReleaseDt, pf.releaseTime - now);
            }
        }

        double dt = std::min(nextFinishDt, nextReleaseDt);
        if (!std::isfinite(dt)) {
            throw std::runtime_error("Global KSP event simulation reached non-finite dt.");
        }
        if (dt <= kEps) {
            if (std::isfinite(nextReleaseDt) && nextReleaseDt > kEps) {
                now += nextReleaseDt;
                continue;
            }
            int bestIdx = active.front();
            for (int idx : active) {
                if (planned[idx].remainingBytes < planned[bestIdx].remainingBytes) {
                    bestIdx = idx;
                }
            }
            planned[bestIdx].remainingBytes = 0.0;
            planned[bestIdx].finishTime = now;
            planned[bestIdx].finished = true;
            ++done;
            continue;
        }

        now += dt;
        for (int idx : active) {
            auto& pf = planned[idx];
            if (pf.finished) {
                continue;
            }
            pf.remainingBytes -= rates[idx] * dt;
            if (pf.remainingBytes <= kEps) {
                pf.remainingBytes = 0.0;
                pf.finishTime = now;
                pf.finished = true;
                ++done;
            }
        }
    }

    std::vector<ScheduledFlow> scheduled;
    scheduled.reserve(scheduledImmediate.size() + planned.size());
    for (const auto& sf : scheduledImmediate) {
        scheduled.push_back(sf);
    }
    for (const auto& pf : planned) {
        ScheduledFlow sf;
        sf.flow = pf.flow;
        sf.corePath = pf.path.nodes;
        sf.sameTorBypass = false;
        sf.serviceStartTime = pf.serviceStartTime;
        sf.finishTime = pf.finishTime;
        sf.bottleneckRate = pf.initialRate > 0.0 ? pf.initialRate : pathBottleneckRate(pf.path, ctx.capacity);
        scheduled.push_back(std::move(sf));
    }

    return scheduled;
}

}  // namespace flsim
