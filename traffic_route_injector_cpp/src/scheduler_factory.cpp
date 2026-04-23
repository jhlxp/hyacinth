#include "scheduler.h"

#include <stdexcept>

#include "eps_ecmp_scheduler.h"
#include "ocs_eps_preset_greedy_scheduler.h"
#include "ocs_eps_preset_dynamic_greedy_scheduler.h"
#include "ocs_eps_global_ksp_scheduler.h"
#include "ocs_eps_large_small_scheduler.h"
#include "pure_ocs_3hop_ksp_scheduler.h"
#include "pure_ocs_ksp_greedy_scheduler.h"
#include "pure_ocs_ksp_scheduler.h"
#include "pure_ocs_pruned_scheduler.h"
#include "strict_queue_greedy_scheduler.h"

namespace flsim {

std::unique_ptr<Scheduler> createScheduler(const SchedulerConfig& config) {
    if (config.name == "eps_ecmp") {
        return std::make_unique<EpsEcmpScheduler>();
    }
    if (config.name == "strict_queue_greedy" ||
        config.name == "ocs_eps_pruned") {
        return std::make_unique<StrictQueueGreedyScheduler>();
    }
    if (config.name == "pure_ocs_ksp") {
        return std::make_unique<PureOcsKspScheduler>(config.kspK);
    }
    if (config.name == "pure_ocs_ksp_greedy") {
        return std::make_unique<PureOcsKspGreedyScheduler>(config.kspK);
    }
    if (config.name == "pure_ocs_pruned") {
        return std::make_unique<PureOcsPrunedScheduler>(config.maxHops, config.maxCandidates);
    }
    if (config.name == "pure_ocs_3hop_preset" ||
        config.name == "pure_ocs_3hop_ksp") {
        return std::make_unique<PureOcs3HopKspScheduler>(config.kspK, config.maxCandidates);
    }
    if (config.name == "ocs_eps_global_ksp") {
        return std::make_unique<OcsEpsGlobalKspScheduler>(config.kspK);
    }
    if (config.name == "ocs_eps_large_small") {
        return std::make_unique<OcsEpsLargeSmallScheduler>(
            config.kspK, config.smallFlowMode, config.smallFlowThreshold);
    }
    if (config.name == "ocs_eps_preset_greedy") {
        return std::make_unique<OcsEpsPresetGreedyScheduler>(
            config.kspK, config.smallFlowThreshold, config.maxCandidates);
    }
    if (config.name == "ocs_eps_preset_dynamic_greedy") {
        return std::make_unique<OcsEpsPresetDynamicGreedyScheduler>(
            config.kspK, config.maxCandidates);
    }
    throw std::runtime_error("Unknown scheduler: " + config.name);
}

}  // namespace flsim
