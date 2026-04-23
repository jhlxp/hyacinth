# ================== Basic Compilation Settings ==================
CC = g++-11
CFLAGS = -Wall -O3 -march=native
INCLUDE = -Iinclude -I.
LIB = -L.

# ================== Directory Definitions ==================
SRC_DIR = src
INC_DIR = include
BUILD_DIR = build
RUN_DIR = run

.PHONY: all clean preclean

# ================== Source and Header Files ==================
OBJS = $(BUILD_DIR)/eventlist.o $(BUILD_DIR)/tcppacket.o $(BUILD_DIR)/pipe.o \
       $(BUILD_DIR)/queue.o $(BUILD_DIR)/queue_lossless.o \
       $(BUILD_DIR)/queue_lossless_input.o $(BUILD_DIR)/queue_lossless_output.o \
       $(BUILD_DIR)/ecnqueue.o $(BUILD_DIR)/tcp.o $(BUILD_DIR)/dctcp.o \
       $(BUILD_DIR)/mtcp.o $(BUILD_DIR)/loggers.o $(BUILD_DIR)/logfile.o \
       $(BUILD_DIR)/clock.o $(BUILD_DIR)/config.o $(BUILD_DIR)/network.o \
       $(BUILD_DIR)/qcn.o $(BUILD_DIR)/exoqueue.o $(BUILD_DIR)/randomqueue.o \
       $(BUILD_DIR)/cbr.o $(BUILD_DIR)/cbrpacket.o $(BUILD_DIR)/sent_packets.o \
       $(BUILD_DIR)/ndp.o $(BUILD_DIR)/ndppacket.o $(BUILD_DIR)/eth_pause_packet.o \
       $(BUILD_DIR)/tcp_periodic.o $(BUILD_DIR)/compositequeue.o \
       $(BUILD_DIR)/prioqueue.o $(BUILD_DIR)/cpqueue.o \
       $(BUILD_DIR)/compositeprioqueue.o $(BUILD_DIR)/switch.o \
       $(BUILD_DIR)/fairpullqueue.o $(BUILD_DIR)/route.o \
       $(BUILD_DIR)/flat_topology.o $(BUILD_DIR)/dag_manager.o \
       $(BUILD_DIR)/hpcc.o $(BUILD_DIR)/intqueue.o \
       $(BUILD_DIR)/bolt.o $(BUILD_DIR)/boltqueue.o

HDRS = $(wildcard $(INC_DIR)/*.h)

# ================== Build Targets ==================
all: preclean $(RUN_DIR)/htsim_ndp_flat $(RUN_DIR)/htsim_dctcp_flat $(RUN_DIR)/htsim_bolt_flat $(RUN_DIR)/htsim_hpcc_flat lib

preclean:
	@$(MAKE) clean

# ---- Static Library: libhtsim.a ----
lib: $(OBJS)
	ar -rvu $(BUILD_DIR)/libhtsim.a $(OBJS)

# ---- Main Executable ----
$(RUN_DIR)/htsim_ndp_flat: $(BUILD_DIR)/main_ndp_flat.o $(OBJS)
	@mkdir -p $(RUN_DIR)
	$(CC) $(CFLAGS) $(INCLUDE) $(BUILD_DIR)/main_ndp_flat.o $(OBJS) -o $@

$(RUN_DIR)/htsim_dctcp_flat: $(BUILD_DIR)/main_dctcp_flat.o $(OBJS)
	@mkdir -p $(RUN_DIR)
	$(CC) $(CFLAGS) $(INCLUDE) $(BUILD_DIR)/main_dctcp_flat.o $(OBJS) -o $@

$(RUN_DIR)/htsim_bolt_flat: $(BUILD_DIR)/main_bolt_flat.o $(OBJS)
	@mkdir -p $(RUN_DIR)
	$(CC) $(CFLAGS) $(INCLUDE) $(BUILD_DIR)/main_bolt_flat.o $(OBJS) -o $@

$(RUN_DIR)/htsim_hpcc_flat: $(BUILD_DIR)/main_hpcc_flat.o $(OBJS)
	@mkdir -p $(RUN_DIR)
	$(CC) $(CFLAGS) $(INCLUDE) $(BUILD_DIR)/main_hpcc_flat.o $(OBJS) -o $@

# ---- Compilation Rule for Each .o File ----
$(BUILD_DIR)/%.o: $(SRC_DIR)/%.cpp $(HDRS)
	@mkdir -p $(BUILD_DIR)
	$(CC) $(CFLAGS) $(INCLUDE) -c $< -o $@

# ---- Cleanup ----
clean:
	rm -rf $(BUILD_DIR)/*.o $(BUILD_DIR)/*.a \
		$(RUN_DIR)/htsim_ndp_flat $(RUN_DIR)/htsim_dctcp_flat \
		$(RUN_DIR)/htsim_bolt_flat $(RUN_DIR)/htsim_hpcc_flat
