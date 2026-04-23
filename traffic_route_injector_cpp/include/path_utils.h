#ifndef FLOW_LEVEL_SIM_PATH_UTILS_H
#define FLOW_LEVEL_SIM_PATH_UTILS_H

#include <functional>
#include <vector>

#include "types.h"

namespace flsim {

std::vector<CandidatePath> enumerateCandidatePaths(int s,
                                                   int t,
                                                   const std::vector<std::vector<double>>& C,
                                                   int numTor,
                                                   int numEps);
std::vector<Edge> pathToEdges(const CandidatePath& p);
double pathBottleneckRate(const CandidatePath& p, const std::vector<std::vector<double>>& C);

std::vector<CandidatePath> enumerateKShortestPaths(int s,
                                                   int t,
                                                   const std::vector<std::vector<double>>& C,
                                                   int K,
                                                   int maxNodeExclusive);
std::vector<CandidatePath> enumeratePrunedOcsPaths(int s,
                                                   int t,
                                                   const std::vector<std::vector<double>>& C,
                                                   int numTor,
                                                   int maxHops,
                                                   int maxCandidates,
                                                   bool forceDirectIfAvailable);
std::vector<CandidatePath> enumerateSingleHopEpsPaths(int s,
                                                      int t,
                                                      const std::vector<std::vector<double>>& C,
                                                      int numTor,
                                                      int numEps);

}  // namespace flsim

#endif
