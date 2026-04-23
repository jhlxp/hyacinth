#include "simulator.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <queue>
#include <stdexcept>
#include <unordered_map>
#include <vector>

#include "dag_task_scheduler.h"
#include "ocs_eps_global_ksp_scheduler.h"
#include "ocs_eps_large_small_scheduler.h"
#include "ocs_eps_preset_dynamic_greedy_scheduler.h"
#include "ocs_eps_preset_greedy_scheduler.h"
#include "path_utils.h"
#include "pure_ocs_ksp_greedy_scheduler.h"
#include "pure_ocs_ksp_scheduler.h"

namespace flsim {
namespace {

uint64_t edgeKey(int u, int v) {
    return (static_cast<uint64_t>(static_cast<uint32_t>(u)) << 32) |
           static_cast<uint32_t>(v);
}

struct CompetitivePlannedFlow {
    size_t scheduledIndex = 0;
    std::vector<Edge> edges;
    double releaseTime = 0.0;
    double remainingBytes = 0.0;
    bool started = false;
    bool finished = false;
};

std::vector<std::vector<double>> buildEdgeBackgroundLoadAtTime(const std::vector<ScheduledFlow>& decidedFlows,
                                                               int coreN,
                                                               double timePoint) {
    const double kEps = 1e-12;
    std::vector<std::vector<double>> load(coreN, std::vector<double>(coreN, 0.0));
    for (const auto& sf : decidedFlows) {
        if (sf.sameTorBypass || sf.corePath.size() <= 1) {
            continue;
        }
        if (sf.serviceStartTime > timePoint + kEps || sf.finishTime <= timePoint + kEps) {
            continue;
        }
        CandidatePath path{sf.corePath};
        for (const auto& edge : pathToEdges(path)) {
            load[edge.first][edge.second] += 1.0;
        }
    }
    return load;
}

void recomputeCompetitiveTiming(std::vector<ScheduledFlow>& scheduled,
                                const std::vector<std::vector<double>>& capacity) {
    const double kEps = 1e-12;

    std::vector<CompetitivePlannedFlow> planned;
    planned.reserve(scheduled.size());

    for (size_t i = 0; i < scheduled.size(); ++i) {
        auto& sf = scheduled[i];
        if (sf.sameTorBypass || sf.corePath.size() <= 1) {
            sf.serviceStartTime = sf.flow.startTime;
            sf.finishTime = sf.flow.startTime;
            sf.bottleneckRate = std::numeric_limits<double>::infinity();
            continue;
        }

        CandidatePath path{sf.corePath};
        auto edges = pathToEdges(path);
        if (edges.empty()) {
            throw std::runtime_error("Scheduled flow has invalid empty core path in concurrent timing recompute.");
        }
        for (const auto& edge : edges) {
            if (capacity[edge.first][edge.second] <= 0.0) {
                throw std::runtime_error("Scheduled flow path has non-positive capacity edge.");
            }
        }
        const double decidedServiceStart = sf.serviceStartTime;

        sf.serviceStartTime = 0.0;
        sf.finishTime = 0.0;
        sf.bottleneckRate = 0.0;

        CompetitivePlannedFlow pf;
        pf.scheduledIndex = i;
        pf.edges = std::move(edges);
        // Keep causality from per-coflow decision phase:
        // later coflows may have delayed release because they observed earlier reservations.
        pf.releaseTime = std::max(sf.flow.startTime, decidedServiceStart);
        pf.remainingBytes = sf.flow.bytes;
        planned.push_back(std::move(pf));
    }

    if (planned.empty()) {
        return;
    }

    int done = 0;
    double now = std::numeric_limits<double>::infinity();
    for (const auto& pf : planned) {
        now = std::min(now, pf.releaseTime);
    }
    if (!std::isfinite(now)) {
        now = 0.0;
    }

    while (done < static_cast<int>(planned.size())) {
        for (auto& pf : planned) {
            if (!pf.finished && pf.remainingBytes <= kEps) {
                pf.finished = true;
                scheduled[pf.scheduledIndex].finishTime = now;
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
                    scheduled[pf.scheduledIndex].serviceStartTime = now;
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
                throw std::runtime_error("No active flow and no future release in concurrent timing recompute.");
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
            auto& sf = scheduled[pf.scheduledIndex];
            double rate = std::numeric_limits<double>::infinity();
            for (const auto& edge : pf.edges) {
                const double cap = capacity[edge.first][edge.second];
                const auto it = edgeActiveCount.find(edgeKey(edge.first, edge.second));
                if (it == edgeActiveCount.end() || it->second <= 0) {
                    throw std::runtime_error("Concurrent timing share accounting failed for an active edge.");
                }
                rate = std::min(rate, cap / static_cast<double>(it->second));
            }
            if (!(rate > 0.0)) {
                throw std::runtime_error("Concurrent timing shared rate must be positive.");
            }
            if (sf.bottleneckRate <= 0.0) {
                sf.bottleneckRate = rate;
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
            throw std::runtime_error("Concurrent timing recompute reached non-finite dt.");
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
            planned[bestIdx].finished = true;
            scheduled[planned[bestIdx].scheduledIndex].finishTime = now;
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
                pf.finished = true;
                scheduled[pf.scheduledIndex].finishTime = now;
                ++done;
            }
        }
    }
}

}  // namespace

FlowLevelSimulator::FlowLevelSimulator(std::vector<std::vector<double>> capacity,
                                       int numTor,
                                       int numEps,
                                       std::unique_ptr<Scheduler> scheduler)
    : capacity_(std::move(capacity)),
      numTor_(numTor),
      numEps_(numEps),
      scheduler_(std::move(scheduler)) {
    if (!scheduler_) {
        throw std::runtime_error("Scheduler must not be null.");
    }
}

SimulationResult FlowLevelSimulator::run(const std::vector<Job>& jobs) const {
    const int coreN = static_cast<int>(capacity_.size());
    std::vector<std::vector<double>> freeTime(coreN, std::vector<double>(coreN, 0.0));

    SimulationResult result;
    if (jobs.empty()) {
        result.finalFreeTime = std::move(freeTime);
        return result;
    }

    const bool countSolveTime = scheduler_->countsSolveTime();
    const double kEps = 1e-12;

    struct ReadyItem {
        size_t index = 0;
        int jobId = -1;
        double readyTime = 0.0;
    };
    struct ReadyCmp {
        bool operator()(const ReadyItem& a, const ReadyItem& b) const {
            if (a.readyTime != b.readyTime) {
                return a.readyTime > b.readyTime;
            }
            return a.jobId > b.jobId;
        }
    };
    struct JobFinishEvent {
        double finishTime = 0.0;
        size_t index = 0;
        int jobId = -1;
    };
    struct JobFinishCmp {
        bool operator()(const JobFinishEvent& a, const JobFinishEvent& b) const {
            if (a.finishTime != b.finishTime) {
                return a.finishTime > b.finishTime;
            }
            return a.jobId > b.jobId;
        }
    };
    struct PlannedFlow {
        size_t scheduledIndex = 0;
        size_t jobIndex = 0;
        std::vector<Edge> edges;
        double releaseTime = 0.0;
        double remainingBytes = 0.0;
        bool finished = false;
    };
    struct RuntimeJobState {
        bool scheduled = false;
        bool finishQueued = false;
        bool finished = false;
        double readyTime = 0.0;
        double schedDelaySec = 0.0;
        double schedStart = 0.0;
        double schedEnd = 0.0;
        double txStart = 0.0;
        double txEnd = 0.0;
        double computeEnd = 0.0;
        double bytesTotal = 0.0;
        int numFlows = 0;
        int pendingCoreFlows = 0;
    };

    DagTaskScheduler dagScheduler(jobs);
    std::priority_queue<ReadyItem, std::vector<ReadyItem>, ReadyCmp> readyQ;
    std::priority_queue<JobFinishEvent, std::vector<JobFinishEvent>, JobFinishCmp> finishQ;
    std::vector<RuntimeJobState> jobStates(jobs.size());
    std::vector<PlannedFlow> plannedFlows;
    plannedFlows.reserve(1024);
    int finishedPlannedFlows = 0;

    auto drainDagReady = [&]() {
        while (!dagScheduler.empty()) {
            const auto n = dagScheduler.popReady();
            const double rt = std::max(jobs[n.index].startTime, n.readyTime);
            readyQ.push(ReadyItem{n.index, n.jobId, rt});
        }
    };

    drainDagReady();
    if (readyQ.empty()) {
        throw std::runtime_error("No ready coflow found in DAG scheduler initialization.");
    }

    std::vector<std::vector<double>> isolatedFreeTime(coreN, std::vector<double>(coreN, 0.0));
    SchedulerContext prepareCtx{capacity_, isolatedFreeTime, numTor_, numEps_};
    scheduler_->prepare(prepareCtx);

    auto tryQueueJobFinish = [&](size_t jobIndex) {
        auto& st = jobStates[jobIndex];
        if (st.finished || st.finishQueued || st.pendingCoreFlows > 0) {
            return;
        }
        const double finishTime = std::max(st.computeEnd, st.txEnd);
        finishQ.push(JobFinishEvent{finishTime, jobIndex, jobs[jobIndex].jobId});
        st.finishQueued = true;
    };

    auto finalizeJob = [&](size_t jobIndex, double finishTime) {
        auto& st = jobStates[jobIndex];
        if (st.finished) {
            return;
        }
        st.finished = true;
        result.maxFinishTime = std::max(result.maxFinishTime, finishTime);

        dagScheduler.markFinished(jobIndex, finishTime);
        drainDagReady();

        const Job& baseJob = jobs[jobIndex];
        if (baseJob.flows.empty()) {
            return;
        }

        SimulationResult::JobStat jobStat;
        jobStat.jobId = baseJob.jobId;
        jobStat.numFlows = st.numFlows;
        jobStat.startTime = st.readyTime;
        jobStat.finishTime = finishTime;
        jobStat.duration = std::max(0.0, finishTime - st.readyTime);
        jobStat.modelId = baseJob.modelId;
        jobStat.roundId = baseJob.roundId;
        jobStat.groupId = baseJob.groupId;
        result.jobStats.push_back(jobStat);
        result.makespan += jobStat.duration;

        SimulationResult::CoflowTimelineStat tl;
        tl.modelId = baseJob.modelId;
        tl.roundId = baseJob.roundId;
        tl.groupId = baseJob.groupId;
        tl.jobId = baseJob.jobId;
        tl.readyTime = st.readyTime;
        tl.schedStartTime = st.schedStart;
        tl.schedEndTime = st.schedEnd;
        tl.schedTime = std::max(0.0, st.schedDelaySec);
        tl.txStartTime = st.txStart;
        tl.txEndTime = st.txEnd;
        tl.txTime = std::max(0.0, st.txEnd - st.txStart);
        tl.bytesTotal = st.bytesTotal;
        tl.numFlows = st.numFlows;
        result.coflowTimelineStats.push_back(tl);
    };

    auto completeFlow = [&](size_t plannedIndex, double finishTime) {
        auto& pf = plannedFlows[plannedIndex];
        if (pf.finished) {
            return;
        }
        pf.finished = true;
        pf.remainingBytes = 0.0;
        ++finishedPlannedFlows;

        auto& sf = result.scheduledFlows[pf.scheduledIndex];
        sf.finishTime = finishTime;
        result.maxFinishTime = std::max(result.maxFinishTime, finishTime);

        auto& st = jobStates[pf.jobIndex];
        st.txEnd = std::max(st.txEnd, finishTime);
        if (st.pendingCoreFlows <= 0) {
            throw std::runtime_error("Flow completion accounting underflow in competitive mode.");
        }
        --st.pendingCoreFlows;
        if (st.pendingCoreFlows == 0) {
            tryQueueJobFinish(pf.jobIndex);
        }

        CandidatePath p{sf.corePath};
        for (const auto& edge : pathToEdges(p)) {
            freeTime[edge.first][edge.second] = std::max(freeTime[edge.first][edge.second], finishTime);
        }
    };

    auto processJobFinishEventsAtNow = [&](double now) {
        while (!finishQ.empty() && finishQ.top().finishTime <= now + kEps) {
            const auto ev = finishQ.top();
            finishQ.pop();
            finalizeJob(ev.index, ev.finishTime);
        }
    };

    auto dispatchReadyJobsAtNow = [&](double now) {
        while (!readyQ.empty() && readyQ.top().readyTime <= now + kEps) {
            const auto item = readyQ.top();
            readyQ.pop();
            auto& st = jobStates[item.index];
            if (st.scheduled) {
                continue;
            }
            st.scheduled = true;

            const Job& baseJob = jobs[item.index];
            const double readyTime = std::max(baseJob.startTime, item.readyTime);
            st.readyTime = readyTime;
            st.schedStart = readyTime;
            st.schedEnd = readyTime;
            st.txStart = readyTime;
            st.txEnd = readyTime;
            st.numFlows = static_cast<int>(baseJob.flows.size());
            st.bytesTotal = 0.0;
            st.pendingCoreFlows = 0;

            if (baseJob.flows.empty()) {
                st.computeEnd = readyTime + std::max(0.0, baseJob.computeTime);
                tryQueueJobFinish(item.index);
                continue;
            }

            Job runtimeJob = baseJob;
            runtimeJob.startTime = readyTime;
            for (auto& flow : runtimeJob.flows) {
                flow.startTime = readyTime;
            }

            SchedulerContext ctx{capacity_, isolatedFreeTime, numTor_, numEps_};
            const auto callStart = std::chrono::high_resolution_clock::now();
            auto scheduled = scheduler_->scheduleJob(runtimeJob, ctx);
            const auto callEnd = std::chrono::high_resolution_clock::now();
            const double measuredSolveWallMs =
                std::chrono::duration<double, std::milli>(callEnd - callStart).count();
            const double solveMs = countSolveTime ? scheduler_->reportedSolveTimeMs(measuredSolveWallMs) : 0.0;

            SimulationResult::SolveCallStat stat;
            stat.jobId = baseJob.jobId;
            stat.numFlows = st.numFlows;
            stat.solveTimeMs = solveMs;
            result.solveCalls.push_back(stat);

            st.schedDelaySec = solveMs * 1e-3;
            st.schedEnd = readyTime + st.schedDelaySec;
            st.txEnd = st.schedEnd;

            bool hasCoreFlow = false;
            double minCoreRelease = std::numeric_limits<double>::infinity();

            for (auto& sf : scheduled) {
                sf.flow.startTime = readyTime;
                sf.serviceStartTime += st.schedDelaySec;
                sf.finishTime = sf.serviceStartTime;
                st.bytesTotal += sf.flow.bytes;

                const size_t sfIndex = result.scheduledFlows.size();
                result.scheduledFlows.push_back(sf);

                if (sf.sameTorBypass || sf.corePath.size() <= 1) {
                    result.scheduledFlows[sfIndex].bottleneckRate = std::numeric_limits<double>::infinity();
                    st.txEnd = std::max(st.txEnd, sf.finishTime);
                    result.maxFinishTime = std::max(result.maxFinishTime, sf.finishTime);
                    continue;
                }

                hasCoreFlow = true;
                minCoreRelease = std::min(minCoreRelease, sf.serviceStartTime);
                CandidatePath path{sf.corePath};
                auto edges = pathToEdges(path);
                if (edges.empty()) {
                    throw std::runtime_error("Scheduled core flow has empty path in competitive mode.");
                }
                for (const auto& edge : edges) {
                    if (capacity_[edge.first][edge.second] <= 0.0) {
                        throw std::runtime_error("Scheduled core flow contains non-positive capacity edge.");
                    }
                }

                PlannedFlow pf;
                pf.scheduledIndex = sfIndex;
                pf.jobIndex = item.index;
                pf.edges = std::move(edges);
                pf.releaseTime = sf.serviceStartTime;
                pf.remainingBytes = sf.flow.bytes;
                plannedFlows.push_back(std::move(pf));
                ++st.pendingCoreFlows;
            }

            st.txStart = hasCoreFlow ? minCoreRelease : st.schedEnd;
            st.computeEnd = readyTime + std::max(0.0, baseJob.computeTime);
            tryQueueJobFinish(item.index);
        }
    };

    double now = std::max(0.0, readyQ.top().readyTime);
    while (dagScheduler.processedCount() < dagScheduler.totalJobs() ||
           finishedPlannedFlows < static_cast<int>(plannedFlows.size())) {
        processJobFinishEventsAtNow(now);
        dispatchReadyJobsAtNow(now);
        processJobFinishEventsAtNow(now);

        std::vector<size_t> active;
        active.reserve(plannedFlows.size());
        double nextReleaseTime = std::numeric_limits<double>::infinity();
        for (size_t i = 0; i < plannedFlows.size(); ++i) {
            const auto& pf = plannedFlows[i];
            if (pf.finished) {
                continue;
            }
            if (pf.releaseTime <= now + kEps) {
                active.push_back(i);
            } else {
                nextReleaseTime = std::min(nextReleaseTime, pf.releaseTime);
            }
        }

        const double nextReadyTime = readyQ.empty() ? std::numeric_limits<double>::infinity() : readyQ.top().readyTime;
        const double nextJobFinishTime =
            finishQ.empty() ? std::numeric_limits<double>::infinity() : finishQ.top().finishTime;

        if (active.empty()) {
            const double nextTime = std::min(nextReleaseTime, std::min(nextReadyTime, nextJobFinishTime));
            if (!std::isfinite(nextTime)) {
                break;
            }
            now = std::max(now, nextTime);
            continue;
        }

        std::unordered_map<uint64_t, int> edgeActiveCount;
        edgeActiveCount.reserve(active.size() * 4);
        for (const auto idx : active) {
            for (const auto& edge : plannedFlows[idx].edges) {
                ++edgeActiveCount[edgeKey(edge.first, edge.second)];
            }
        }

        std::vector<double> rates(plannedFlows.size(), 0.0);
        double nextFlowFinishDt = std::numeric_limits<double>::infinity();
        for (const auto idx : active) {
            const auto& pf = plannedFlows[idx];
            double rate = std::numeric_limits<double>::infinity();
            for (const auto& edge : pf.edges) {
                const auto it = edgeActiveCount.find(edgeKey(edge.first, edge.second));
                if (it == edgeActiveCount.end() || it->second <= 0) {
                    throw std::runtime_error("Missing active edge accounting in competitive mode.");
                }
                rate = std::min(rate, capacity_[edge.first][edge.second] / static_cast<double>(it->second));
            }
            if (!(rate > 0.0)) {
                throw std::runtime_error("Non-positive active rate in competitive mode.");
            }
            rates[idx] = rate;
            auto& sf = result.scheduledFlows[pf.scheduledIndex];
            if (sf.bottleneckRate <= 0.0) {
                sf.bottleneckRate = rate;
            } else {
                sf.bottleneckRate = std::min(sf.bottleneckRate, rate);
            }
            nextFlowFinishDt = std::min(nextFlowFinishDt, pf.remainingBytes / rate);
        }

        double nextTime = now + nextFlowFinishDt;
        nextTime = std::min(nextTime, nextReleaseTime);
        nextTime = std::min(nextTime, nextReadyTime);
        nextTime = std::min(nextTime, nextJobFinishTime);
        if (!std::isfinite(nextTime)) {
            throw std::runtime_error("Competitive event loop reached non-finite next event time.");
        }

        const double dt = std::max(0.0, nextTime - now);
        if (dt <= kEps) {
            now = nextTime;
            bool progressed = false;
            for (const auto idx : active) {
                if (plannedFlows[idx].remainingBytes <= kEps) {
                    completeFlow(idx, now);
                    progressed = true;
                }
            }
            if (!progressed) {
                size_t pick = active.front();
                for (const auto idx : active) {
                    if (plannedFlows[idx].remainingBytes < plannedFlows[pick].remainingBytes) {
                        pick = idx;
                    }
                }
                completeFlow(pick, now);
            }
            continue;
        }

        now = nextTime;
        for (const auto idx : active) {
            auto& pf = plannedFlows[idx];
            if (pf.finished) {
                continue;
            }
            pf.remainingBytes -= rates[idx] * dt;
            if (pf.remainingBytes <= kEps) {
                completeFlow(idx, now);
            }
        }
    }

    processJobFinishEventsAtNow(now);
    if (dagScheduler.processedCount() != dagScheduler.totalJobs()) {
        throw std::runtime_error("Dependency graph is cyclic or unresolved jobs remain.");
    }

    result.finalFreeTime = std::move(freeTime);
    std::sort(result.scheduledFlows.begin(), result.scheduledFlows.end(), [](const ScheduledFlow& a, const ScheduledFlow& b) {
        if (a.flow.jobId != b.flow.jobId) {
            return a.flow.jobId < b.flow.jobId;
        }
        return a.flow.flowId < b.flow.flowId;
    });
    std::sort(result.jobStats.begin(), result.jobStats.end(), [](const SimulationResult::JobStat& a,
                                                                 const SimulationResult::JobStat& b) {
        if (a.startTime != b.startTime) {
            return a.startTime < b.startTime;
        }
        return a.jobId < b.jobId;
    });
    std::sort(result.coflowTimelineStats.begin(),
              result.coflowTimelineStats.end(),
              [](const SimulationResult::CoflowTimelineStat& a,
                 const SimulationResult::CoflowTimelineStat& b) {
                  if (a.readyTime != b.readyTime) {
                      return a.readyTime < b.readyTime;
                  }
                  return a.jobId < b.jobId;
              });
    return result;
}

}  // namespace flsim
