#ifndef FLOW_LEVEL_SIM_TOPOLOGY_READER_H
#define FLOW_LEVEL_SIM_TOPOLOGY_READER_H

#include <string>
#include <vector>

#include "types.h"

namespace flsim {

TopologyInput readTopologyFile(const std::string& filename);
std::vector<int> inferAggParentTor(const std::vector<std::vector<int>>& fullAdj,
                                   int numTor,
                                   int numEps);
std::vector<std::vector<double>> buildCoreCapacityMatrix(const std::vector<std::vector<int>>& fullAdj,
                                                         int numTor,
                                                         int numEps,
                                                         double rateTorTor,
                                                         double rateTorEps);

}  // namespace flsim

#endif
