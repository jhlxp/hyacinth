CXX := g++
CXXFLAGS := -std=c++17 -O2 -Wall -Wextra -Iinclude -MMD -MP
LDFLAGS :=

TARGET_ROUTE := bin/route_trace_dep_injector
COMMON_SRCS := $(filter-out src/main.cpp src/route_trace_dep_main.cpp,$(wildcard src/*.cpp))
COMMON_OBJS := $(COMMON_SRCS:.cpp=.o)
ROUTE_OBJ := src/route_trace_dep_main.o
DEPS := $(COMMON_OBJS:.o=.d) $(ROUTE_OBJ:.o=.d)
TARGETS := $(TARGET_ROUTE)

.PHONY: all clean preclean

all: preclean $(TARGETS)

preclean:
	@$(MAKE) clean

$(TARGET_ROUTE): $(COMMON_OBJS) $(ROUTE_OBJ)
	@mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -o $@ $^ $(LDFLAGS)

src/%.o: src/%.cpp
	$(CXX) $(CXXFLAGS) -c $< -o $@

clean:
	rm -f src/*.o src/*.d $(TARGET_ROUTE)

-include $(DEPS)
