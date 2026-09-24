# 定义工具变量
JOBS ?= $(shell command -v nproc >/dev/null 2>&1 && nproc || sysctl -n hw.logicalcpu)
BUILD_TYPE ?= Release
NPROC := $(JOBS)

ifeq ($(BUILD_TYPE),Debug)
override CFLAGS := -O0 -g3 $(CFLAGS)
override CXXFLAGS := -O0 -g3 $(CXXFLAGS)
endif
CONFIGURE = ./configure
MAKE = make -j$(NPROC)
CMAKE = cmake
RSYNC = rsync -a --delete --exclude='.git' --exclude='build'
# Refresh without --delete: overlays changed source files onto the in-tree
# build copy while keeping generated files and objects for incremental builds.
RSYNC_REFRESH = rsync -a --exclude='.git' --exclude='build'
# Cargo projects legitimately ship a build/ module dir (e.g. libsigrok-sys/build/
# holds the build-script sources), so do NOT exclude 'build'. Exclude cargo's
# root-anchored target/ output instead.
RSYNC_CARGO = rsync -a --delete --exclude='.git' --exclude='/target'
RSYNC_CARGO_REFRESH = rsync -a --exclude='.git' --exclude='/target'

# 交叉编译开关：CROSS=win32 使用 x86_64-w64-mingw32 工具链
# 用法: make CROSS=win32 install-libsigrok
ifeq ($(CROSS),win32)
	SUFFIX := -win32
	EXE_SUFFIX := .exe
	HOST := x86_64-w64-mingw32
	CONFIGURE_HOST := --host=$(HOST)
	# 使用 mingw-w64-pkg-config 包装器，自动指向 /usr/$(HOST)/lib/pkgconfig，隔离宿主依赖
	export PKG_CONFIG := $(HOST)-pkg-config
else
	# 根据操作系统设置后缀
	UNAME_S := $(shell uname -s)
	ifeq ($(UNAME_S),Linux)
		SUFFIX =
		EXE_SUFFIX =
	else ifeq ($(UNAME_S),Darwin)
		SUFFIX = -darwin
		EXE_SUFFIX =
	else
		SUFFIX = -win32
		EXE_SUFFIX = .exe
	endif
endif

PREFIX = $(shell pwd)/sr$(SUFFIX)
BUILD_DIR = build$(SUFFIX)

ifeq ($(CROSS),win32)
	TOOLCHAIN_CC := $(HOST)-gcc
	TOOLCHAIN_CXX := $(HOST)-g++
else
	TOOLCHAIN_CC := $(if $(strip $(CC)),$(firstword $(CC)),cc)
	TOOLCHAIN_CXX := $(if $(strip $(CXX)),$(firstword $(CXX)),c++)
endif
TOOLCHAIN_SIG := $(shell printf '%s\n' "$$($(TOOLCHAIN_CC) -print-file-name=crtbeginS.o 2>/dev/null)" "$$($(TOOLCHAIN_CXX) -print-file-name=crtbeginS.o 2>/dev/null)" | { command -v sha256sum >/dev/null 2>&1 && sha256sum || shasum -a 256; } | cut -d' ' -f1)
TOOLCHAIN_STAMP := $(BUILD_DIR)/.toolchain-$(TOOLCHAIN_SIG).stamp

# 统一导出环境变量 (全流程生效，无需重复配置)
export PKG_CONFIG_PATH := $(PREFIX)/lib/pkgconfig:$(PREFIX)/lib64/pkgconfig:$(PKG_CONFIG_PATH)
export LD_LIBRARY_PATH := $(PREFIX)/lib:$(PREFIX)/lib64:$(LD_LIBRARY_PATH)
export PATH := $(PREFIX)/bin:$(PATH)
export ACLOCAL_PATH := $(PREFIX)/share/aclocal:$(ACLOCAL_PATH)
export CPPFLAGS := -I$(PREFIX)/include $(CPPFLAGS)
export LDFLAGS := -L$(PREFIX)/lib -L$(PREFIX)/lib64 $(LDFLAGS)

# 项目配置
LIBSIGROK_DIR = $(BUILD_DIR)/libsigrok
LIBSIGROKDECODE_DIR = $(BUILD_DIR)/libsigrokdecode
PULSEVIEW_DIR = $(BUILD_DIR)/pulseview
SLOGICVIEW_DIR = $(BUILD_DIR)/slogicview
SIGROK_CLI_DIR = $(BUILD_DIR)/sigrok-cli
ALL_LOGIC_DIR = $(BUILD_DIR)/all-logic
SIGROK_BRIDGE_DIR = $(BUILD_DIR)/sigrok-bridge
NGSCOPECLIENT_DIR = $(BUILD_DIR)/ngscopeclient

LIBSIGROK_BUILD_SYSTEM = autotools
LIBSIGROK_CONFIGURE_OPTS = --disable-all-drivers --enable-sipeed-slogic-analyzer --disable-bindings --enable-cxx --enable-static --enable-shared
# 交叉编译 win32 时无 glibmm/libsigc++ 依赖，关掉 cxx 绑定
ifeq ($(CROSS),win32)
LIBSIGROK_CONFIGURE_OPTS = --disable-all-drivers --enable-sipeed-slogic-analyzer --disable-bindings --enable-static --enable-shared
endif
LIBSIGROKDECODE_BUILD_SYSTEM = autotools
LIBSIGROKDECODE_CONFIGURE_OPTS = --disable-shared --enable-static
PULSEVIEW_BUILD_SYSTEM = cmake
PULSEVIEW_CONFIGURE_OPTS = -DCMAKE_BUILD_TYPE=$(BUILD_TYPE) -DBoost_USE_STATIC_LIBS=ON -DSTATIC_PKGDEPS_LIBS=ON
SLOGICVIEW_BUILD_SYSTEM = cmake
SLOGICVIEW_CONFIGURE_OPTS = $(PULSEVIEW_CONFIGURE_OPTS) -DSLOGICVIEW_VERSION=$(RELEASE_VERSION)
SIGROK_CLI_BUILD_SYSTEM = autotools
# libsigrokdecode 为静态库，用 --static 让 pkg-config 展开其私有依赖 (python 等)，
# 否则最终链接缺少 Py* 符号。该方式不污染 configure 的编译器自检 (不进 LIBS)。
SIGROK_CLI_CONFIGURE_OPTS = PKG_CONFIG="pkg-config --static"
# ALL LOGIC (DSView fork) 自带 libsigrok4DSL/libsigrokdecode4DSL，不依赖上面的 sigrok 组件
ALL_LOGIC_BUILD_SYSTEM = cmake
ALL_LOGIC_CONFIGURE_OPTS = -DCMAKE_BUILD_TYPE=$(BUILD_TYPE)
# ngscopeclient (scopehal-apps): Vulkan/GLFW GUI, self-contained via its lib
# submodule (the scopehal fork). Only on the glibc Linux target and macOS.
NGSCOPECLIENT_BUILD_SYSTEM = cmake
NGSCOPECLIENT_CONFIGURE_OPTS = -DCMAKE_BUILD_TYPE=$(BUILD_TYPE) -DDISABLE_PCH=ON -DBUILD_DOCS=OFF -DBUILD_TESTING=OFF -G Ninja
# scopehal-apps derives its version from `git describe`, but sources are synced
# into the build without .git; the host driver computes the version and passes
# it in so CMake skips git (see build/targets/*/build[-in-container]).
ifneq ($(strip $(NGSCOPECLIENT_PKG_VERSION)),)
NGSCOPECLIENT_CONFIGURE_OPTS += -DNGSCOPECLIENT_PACKAGE_VERSION=$(NGSCOPECLIENT_PKG_VERSION) -DNGSCOPECLIENT_PACKAGE_VERSION_LONG=$(NGSCOPECLIENT_PKG_VERSION_LONG)
endif
# sigrok-bridge (Rust): libsigrok-sys builds its own static libsigrok + C deps.
CARGO ?= cargo
CARGO_BUILD_FLAGS ?= --release

# 通用的构建模板
define CONFIGURE_TEMPLATE
	@echo "[$(1)] Running configure..."
	$(if $(filter autotools,$(2)),\
		cd $(3) && $(CONFIGURE) $(CONFIGURE_HOST) --prefix=$(PREFIX) $(4),\
		cd $(3) && $(CMAKE) -Bbuild -DCMAKE_INSTALL_PREFIX=$(PREFIX) $(4))
endef

define BUILD_TEMPLATE
	@$(RSYNC_REFRESH) $(1)/ $(3)/
	@echo "[$(1)] Building..."
	$(if $(filter autotools,$(2)),\
		cd $(3) && $(MAKE),\
		cd $(3) && $(CMAKE) --build build -j$(NPROC))
endef

define INSTALL_TEMPLATE
	@echo "[$(1)] Installing..."
	$(if $(filter autotools,$(2)),\
		cd $(3) && $(MAKE) install,\
		cd $(3) && $(CMAKE) --build build --target install)
endef

define CLEAN_TEMPLATE
	@echo "[$(1)] Cleaning..."
	-$(if $(filter autotools,$(2)),\
		cd $(3) && $(MAKE) clean 2>/dev/null || true,\
		cd $(3) && $(CMAKE) --build build --target clean 2>/dev/null || true)
endef

# 默认目标
.DEFAULT_GOAL := all
all: install

# ==============================================
# 准备步骤
# ==============================================
prepare: $(LIBSIGROK_DIR)/configure $(LIBSIGROKDECODE_DIR)/configure $(PULSEVIEW_DIR) $(SLOGICVIEW_DIR) $(SIGROK_CLI_DIR)/configure
	@echo "=== Build Environment ==="
	@echo "PREFIX:          $(PREFIX)"
	@echo "BUILD_DIR:       $(BUILD_DIR)"
	@echo "PKG_CONFIG_PATH: $(PKG_CONFIG_PATH)"
	@echo "LD_LIBRARY_PATH: $(LD_LIBRARY_PATH)"
	@echo "Parallel Jobs:   $(NPROC)"
	@echo "========================="

$(TOOLCHAIN_STAMP):
	@mkdir -p $(BUILD_DIR)
	@rm -f $(BUILD_DIR)/.toolchain-*.stamp
	@touch $@

# libsigrok 源码同步和autogen
$(LIBSIGROK_DIR)/configure: libsigrok/configure.ac libsigrok/Makefile.am
	@echo "[libsigrok] Syncing source code..."
	@mkdir -p $(BUILD_DIR)
	@$(RSYNC) libsigrok/ $(LIBSIGROK_DIR)/
	@echo "[libsigrok] Running autogen.sh..."
	@cd $(LIBSIGROK_DIR) && sh ./autogen.sh

# libsigrokdecode 源码同步和autogen
$(LIBSIGROKDECODE_DIR)/configure: libsigrokdecode/configure.ac libsigrokdecode/Makefile.am
	@echo "[libsigrokdecode] Syncing source code..."
	@mkdir -p $(BUILD_DIR)
	@$(RSYNC) libsigrokdecode/ $(LIBSIGROKDECODE_DIR)/
	@echo "[libsigrokdecode] Running autogen.sh..."
	@cd $(LIBSIGROKDECODE_DIR) && sh ./autogen.sh

# pulseview 源码同步
$(PULSEVIEW_DIR): pulseview/CMakeLists.txt
	@echo "[pulseview] Syncing source code..."
	@mkdir -p $(BUILD_DIR)
	@$(RSYNC) pulseview/ $(PULSEVIEW_DIR)/

# SLogicView source synchronization
$(SLOGICVIEW_DIR): slogicview/CMakeLists.txt
	@echo "[slogicview] Syncing source code..."
	@mkdir -p $(BUILD_DIR)
	@$(RSYNC) slogicview/ $(SLOGICVIEW_DIR)/

# ALL LOGIC source synchronization
$(ALL_LOGIC_DIR): all-logic/CMakeLists.txt
	@echo "[all-logic] Syncing source code..."
	@mkdir -p $(BUILD_DIR)
	@$(RSYNC) all-logic/ $(ALL_LOGIC_DIR)/

# sigrok-bridge source synchronization
$(SIGROK_BRIDGE_DIR): sigrok-bridge/Cargo.toml
	@echo "[sigrok-bridge] Syncing source code..."
	@mkdir -p $(BUILD_DIR)
	@$(RSYNC_CARGO) sigrok-bridge/ $(SIGROK_BRIDGE_DIR)/

# ngscopeclient source synchronization
$(NGSCOPECLIENT_DIR): ngscopeclient/CMakeLists.txt
	@echo "[ngscopeclient] Syncing source code..."
	@mkdir -p $(BUILD_DIR)
	@$(RSYNC) ngscopeclient/ $(NGSCOPECLIENT_DIR)/

# sigrok-cli 源码同步和autogen
$(SIGROK_CLI_DIR)/configure: sigrok-cli/configure.ac sigrok-cli/Makefile.am
	@echo "[sigrok-cli] Syncing source code..."
	@mkdir -p $(BUILD_DIR)
	@$(RSYNC) sigrok-cli/ $(SIGROK_CLI_DIR)/
	@echo "[sigrok-cli] Running autogen.sh..."
	@cd $(SIGROK_CLI_DIR) && sh ./autogen.sh

# ==============================================
# libsigrok 目标
# ==============================================
configure-libsigrok: $(LIBSIGROK_DIR)/Makefile
$(LIBSIGROK_DIR)/Makefile: $(LIBSIGROK_DIR)/configure $(TOOLCHAIN_STAMP)
	$(call CONFIGURE_TEMPLATE,libsigrok,$(LIBSIGROK_BUILD_SYSTEM),$(LIBSIGROK_DIR),$(LIBSIGROK_CONFIGURE_OPTS))

build-libsigrok: configure-libsigrok
	$(call BUILD_TEMPLATE,libsigrok,$(LIBSIGROK_BUILD_SYSTEM),$(LIBSIGROK_DIR))

install-libsigrok: build-libsigrok
	$(call INSTALL_TEMPLATE,libsigrok,$(LIBSIGROK_BUILD_SYSTEM),$(LIBSIGROK_DIR))

update-libsigrok:
	@echo "[libsigrok] Syncing source code..."
	@$(RSYNC) libsigrok/ $(LIBSIGROK_DIR)/
	$(call BUILD_TEMPLATE,libsigrok,$(LIBSIGROK_BUILD_SYSTEM),$(LIBSIGROK_DIR))
	$(call INSTALL_TEMPLATE,libsigrok,$(LIBSIGROK_BUILD_SYSTEM),$(LIBSIGROK_DIR))

clean-libsigrok:
	$(call CLEAN_TEMPLATE,libsigrok,$(LIBSIGROK_BUILD_SYSTEM),$(LIBSIGROK_DIR))

# ==============================================
# libsigrokdecode 目标
# ==============================================
configure-libsigrokdecode: $(LIBSIGROKDECODE_DIR)/Makefile
$(LIBSIGROKDECODE_DIR)/Makefile: $(LIBSIGROKDECODE_DIR)/configure $(TOOLCHAIN_STAMP)
	$(call CONFIGURE_TEMPLATE,libsigrokdecode,$(LIBSIGROKDECODE_BUILD_SYSTEM),$(LIBSIGROKDECODE_DIR),$(LIBSIGROKDECODE_CONFIGURE_OPTS))

build-libsigrokdecode: configure-libsigrokdecode
	$(call BUILD_TEMPLATE,libsigrokdecode,$(LIBSIGROKDECODE_BUILD_SYSTEM),$(LIBSIGROKDECODE_DIR))

install-libsigrokdecode: build-libsigrokdecode
	$(call INSTALL_TEMPLATE,libsigrokdecode,$(LIBSIGROKDECODE_BUILD_SYSTEM),$(LIBSIGROKDECODE_DIR))

update-libsigrokdecode:
	@echo "[libsigrokdecode] Syncing source code..."
	@$(RSYNC) libsigrokdecode/ $(LIBSIGROKDECODE_DIR)/
	$(call BUILD_TEMPLATE,libsigrokdecode,$(LIBSIGROKDECODE_BUILD_SYSTEM),$(LIBSIGROKDECODE_DIR))
	$(call INSTALL_TEMPLATE,libsigrokdecode,$(LIBSIGROKDECODE_BUILD_SYSTEM),$(LIBSIGROKDECODE_DIR))

clean-libsigrokdecode:
	$(call CLEAN_TEMPLATE,libsigrokdecode,$(LIBSIGROKDECODE_BUILD_SYSTEM),$(LIBSIGROKDECODE_DIR))

# ==============================================
# pulseview 目标
# ==============================================
configure-pulseview: $(PULSEVIEW_DIR)/build/CMakeCache.txt
install-sigrok-dependencies: $(PREFIX)/.sigrok-dependencies-installed
$(PREFIX)/.sigrok-dependencies-installed: install-libsigrok install-libsigrokdecode
	@touch $@

$(PULSEVIEW_DIR)/build/CMakeCache.txt: $(PULSEVIEW_DIR) $(PREFIX)/.sigrok-dependencies-installed $(TOOLCHAIN_STAMP)
	$(call CONFIGURE_TEMPLATE,pulseview,$(PULSEVIEW_BUILD_SYSTEM),$(PULSEVIEW_DIR),$(PULSEVIEW_CONFIGURE_OPTS))

build-pulseview: configure-pulseview
	$(call BUILD_TEMPLATE,pulseview,$(PULSEVIEW_BUILD_SYSTEM),$(PULSEVIEW_DIR))

install-pulseview: build-pulseview
	$(call INSTALL_TEMPLATE,pulseview,$(PULSEVIEW_BUILD_SYSTEM),$(PULSEVIEW_DIR))

update-pulseview:
	@echo "[pulseview] Syncing source code..."
	@$(RSYNC) pulseview/ $(PULSEVIEW_DIR)/
	$(call BUILD_TEMPLATE,pulseview,$(PULSEVIEW_BUILD_SYSTEM),$(PULSEVIEW_DIR))
	$(call INSTALL_TEMPLATE,pulseview,$(PULSEVIEW_BUILD_SYSTEM),$(PULSEVIEW_DIR))

clean-pulseview:
	$(call CLEAN_TEMPLATE,pulseview,$(PULSEVIEW_BUILD_SYSTEM),$(PULSEVIEW_DIR))

# ==============================================
# SLogicView targets
# ==============================================
configure-slogicview: $(SLOGICVIEW_DIR)/build/CMakeCache.txt

$(SLOGICVIEW_DIR)/build/CMakeCache.txt: $(SLOGICVIEW_DIR) $(PREFIX)/.sigrok-dependencies-installed $(TOOLCHAIN_STAMP)
	$(call CONFIGURE_TEMPLATE,slogicview,$(SLOGICVIEW_BUILD_SYSTEM),$(SLOGICVIEW_DIR),$(SLOGICVIEW_CONFIGURE_OPTS))

build-slogicview: configure-slogicview
	$(call BUILD_TEMPLATE,slogicview,$(SLOGICVIEW_BUILD_SYSTEM),$(SLOGICVIEW_DIR))

install-slogicview: build-slogicview
	$(call INSTALL_TEMPLATE,slogicview,$(SLOGICVIEW_BUILD_SYSTEM),$(SLOGICVIEW_DIR))

update-slogicview:
	@echo "[slogicview] Syncing source code..."
	@$(RSYNC) slogicview/ $(SLOGICVIEW_DIR)/
	$(call BUILD_TEMPLATE,slogicview,$(SLOGICVIEW_BUILD_SYSTEM),$(SLOGICVIEW_DIR))
	$(call INSTALL_TEMPLATE,slogicview,$(SLOGICVIEW_BUILD_SYSTEM),$(SLOGICVIEW_DIR))

clean-slogicview:
	$(call CLEAN_TEMPLATE,slogicview,$(SLOGICVIEW_BUILD_SYSTEM),$(SLOGICVIEW_DIR))

# ==============================================
# sigrok-cli 目标
# ==============================================
configure-sigrok-cli: $(SIGROK_CLI_DIR)/Makefile
$(SIGROK_CLI_DIR)/Makefile: $(SIGROK_CLI_DIR)/configure $(PREFIX)/.sigrok-dependencies-installed $(TOOLCHAIN_STAMP)
	$(call CONFIGURE_TEMPLATE,sigrok-cli,$(SIGROK_CLI_BUILD_SYSTEM),$(SIGROK_CLI_DIR),$(SIGROK_CLI_CONFIGURE_OPTS))

build-sigrok-cli: configure-sigrok-cli
	$(call BUILD_TEMPLATE,sigrok-cli,$(SIGROK_CLI_BUILD_SYSTEM),$(SIGROK_CLI_DIR))

install-sigrok-cli: build-sigrok-cli
	$(call INSTALL_TEMPLATE,sigrok-cli,$(SIGROK_CLI_BUILD_SYSTEM),$(SIGROK_CLI_DIR))

update-sigrok-cli:
	@echo "[sigrok-cli] Syncing source code..."
	@$(RSYNC) sigrok-cli/ $(SIGROK_CLI_DIR)/
	$(call BUILD_TEMPLATE,sigrok-cli,$(SIGROK_CLI_BUILD_SYSTEM),$(SIGROK_CLI_DIR))
	$(call INSTALL_TEMPLATE,sigrok-cli,$(SIGROK_CLI_BUILD_SYSTEM),$(SIGROK_CLI_DIR))

clean-sigrok-cli:
	$(call CLEAN_TEMPLATE,sigrok-cli,$(SIGROK_CLI_BUILD_SYSTEM),$(SIGROK_CLI_DIR))

# ==============================================
# ALL LOGIC 目标 (自带 sigrok 栈，不依赖共享前缀组件)
# ==============================================
configure-all-logic: $(ALL_LOGIC_DIR)/build/CMakeCache.txt

$(ALL_LOGIC_DIR)/build/CMakeCache.txt: $(ALL_LOGIC_DIR) $(TOOLCHAIN_STAMP)
	$(call CONFIGURE_TEMPLATE,all-logic,$(ALL_LOGIC_BUILD_SYSTEM),$(ALL_LOGIC_DIR),$(ALL_LOGIC_CONFIGURE_OPTS))

build-all-logic: configure-all-logic
	$(call BUILD_TEMPLATE,all-logic,$(ALL_LOGIC_BUILD_SYSTEM),$(ALL_LOGIC_DIR))

install-all-logic: build-all-logic
	$(call INSTALL_TEMPLATE,all-logic,$(ALL_LOGIC_BUILD_SYSTEM),$(ALL_LOGIC_DIR))

update-all-logic:
	@echo "[all-logic] Syncing source code..."
	@$(RSYNC) all-logic/ $(ALL_LOGIC_DIR)/
	$(call BUILD_TEMPLATE,all-logic,$(ALL_LOGIC_BUILD_SYSTEM),$(ALL_LOGIC_DIR))
	$(call INSTALL_TEMPLATE,all-logic,$(ALL_LOGIC_BUILD_SYSTEM),$(ALL_LOGIC_DIR))

clean-all-logic:
	$(call CLEAN_TEMPLATE,all-logic,$(ALL_LOGIC_BUILD_SYSTEM),$(ALL_LOGIC_DIR))

# ==============================================
# sigrok-bridge 目标 (Rust; libsigrok-sys 自带静态 libsigrok，不依赖共享前缀)
# ==============================================
configure-sigrok-bridge: $(SIGROK_BRIDGE_DIR)

build-sigrok-bridge: $(SIGROK_BRIDGE_DIR) $(TOOLCHAIN_STAMP)
	@$(RSYNC_CARGO_REFRESH) sigrok-bridge/ $(SIGROK_BRIDGE_DIR)/
	@echo "[sigrok-bridge] cargo build $(CARGO_BUILD_FLAGS) -p sigrok-bridge"
	cd $(SIGROK_BRIDGE_DIR) && $(CARGO) build $(CARGO_BUILD_FLAGS) -p sigrok-bridge

install-sigrok-bridge: build-sigrok-bridge
	@echo "[sigrok-bridge] Installing to $(PREFIX)..."
	@mkdir -p $(PREFIX)/bin
	cp $(SIGROK_BRIDGE_DIR)/target/release/sigrok-bridge$(EXE_SUFFIX) $(PREFIX)/bin/

clean-sigrok-bridge:
	@echo "[sigrok-bridge] Cleaning..."
	-cd $(SIGROK_BRIDGE_DIR) && $(CARGO) clean 2>/dev/null || true

# ==============================================
# ngscopeclient 目标 (scopehal-apps; Vulkan GUI，自带 lib fork，不依赖共享前缀)
# ==============================================
configure-ngscopeclient: $(NGSCOPECLIENT_DIR)/build/CMakeCache.txt

$(NGSCOPECLIENT_DIR)/build/CMakeCache.txt: $(NGSCOPECLIENT_DIR) $(TOOLCHAIN_STAMP)
	$(call CONFIGURE_TEMPLATE,ngscopeclient,$(NGSCOPECLIENT_BUILD_SYSTEM),$(NGSCOPECLIENT_DIR),$(NGSCOPECLIENT_CONFIGURE_OPTS))

build-ngscopeclient: configure-ngscopeclient
	$(call BUILD_TEMPLATE,ngscopeclient,$(NGSCOPECLIENT_BUILD_SYSTEM),$(NGSCOPECLIENT_DIR))

# scopehal-apps' cmake install layout is not relied upon; copy the proven
# artifacts (binary + the two shared libs + runtime resources) into $(PREFIX)
# so the per-platform packagers read a uniform bin/lib/share tree.
install-ngscopeclient: build-ngscopeclient
	@echo "[ngscopeclient] Installing to $(PREFIX)..."
	@mkdir -p $(PREFIX)/bin $(PREFIX)/lib $(PREFIX)/share/ngscopeclient $(PREFIX)/share/scopehal
	cp $(NGSCOPECLIENT_DIR)/build/src/ngscopeclient/ngscopeclient$(EXE_SUFFIX) $(PREFIX)/bin/
	cp $(NGSCOPECLIENT_DIR)/build/lib/scopehal/libscopehal.* $(PREFIX)/lib/
	cp $(NGSCOPECLIENT_DIR)/build/lib/scopeprotocols/libscopeprotocols.* $(PREFIX)/lib/
	@for d in shaders fonts icons masks channels md; do \
		if [ -d $(NGSCOPECLIENT_DIR)/build/src/ngscopeclient/$$d ]; then \
			cp -r $(NGSCOPECLIENT_DIR)/build/src/ngscopeclient/$$d $(PREFIX)/share/ngscopeclient/; \
		fi; \
	done
	-@cp -r $(NGSCOPECLIENT_DIR)/build/lib/scopehal/shaders $(PREFIX)/share/scopehal/ 2>/dev/null || true
	-@cp -r $(NGSCOPECLIENT_DIR)/build/lib/scopeprotocols/shaders $(PREFIX)/share/scopehal/ 2>/dev/null || true

clean-ngscopeclient:
	$(call CLEAN_TEMPLATE,ngscopeclient,$(NGSCOPECLIENT_BUILD_SYSTEM),$(NGSCOPECLIENT_DIR))

# ==============================================
# 全局目标
# ==============================================
# sigrok-cli 仅在本机/Linux 构建链路中启用，交叉编译 win32 时跳过
EXTRA_BUILD_TARGETS = build-sigrok-cli
EXTRA_INSTALL_TARGETS = install-sigrok-cli
ifeq ($(CROSS),win32)
EXTRA_BUILD_TARGETS =
EXTRA_INSTALL_TARGETS =
endif

build: build-libsigrok build-libsigrokdecode build-pulseview build-slogicview $(EXTRA_BUILD_TARGETS)
	@echo "All projects built successfully"

install: install-libsigrok install-libsigrokdecode install-pulseview install-slogicview $(EXTRA_INSTALL_TARGETS)
	@echo "All projects installed to $(PREFIX)"

# 直接运行 PulseView
run: install
	@echo "Running PulseView..."
	@$(PREFIX)/bin/pulseview$(EXE_SUFFIX)

# 生成 AppImage 包
appimage: install
	@echo "Generating AppImage package..."
	@bash ./package_pulseview.sh
	@echo "AppImage generated: PulseView-*.AppImage"

# 清理构建文件
clean: clean-libsigrok clean-libsigrokdecode clean-pulseview clean-slogicview clean-sigrok-cli
	@echo "Clean completed"

# 完全清理
distclean:
	@echo "Removing build directories..."
	@rm -rf $(BUILD_DIR) $(PREFIX) AppDir linuxdeploy-x86_64.AppImage *.AppImage
	@echo "Full clean completed"

# 帮助信息
help:
	@echo "=== Sigrok Projects Build System ==="
	@echo ""
	@echo "Global targets:"
	@echo "  all        - Default: build and install all projects"
	@echo "  prepare    - Prepare source code and show environment"
	@echo "  build      - Build all projects"
	@echo "  install    - Install all projects to local prefix ($(PREFIX))"
	@echo "  run        - Run PulseView directly (no system install needed)"
	@echo "  appimage   - Generate standalone AppImage package"
	@echo "  clean      - Clean build artifacts"
	@echo "  distclean  - Remove all build files and output"
	@echo "  help       - Show this help message"
	@echo ""
	@echo "Per-project targets:"
	@echo "  configure-libsigrok      - Configure libsigrok"
	@echo "  build-libsigrok          - Build libsigrok"
	@echo "  install-libsigrok        - Install libsigrok"
	@echo "  update-libsigrok         - Incremental sync and rebuild libsigrok"
	@echo "  clean-libsigrok          - Clean libsigrok build files"
	@echo ""
	@echo "  configure-libsigrokdecode - Configure libsigrokdecode"
	@echo "  build-libsigrokdecode    - Build libsigrokdecode"
	@echo "  install-libsigrokdecode  - Install libsigrokdecode"
	@echo "  update-libsigrokdecode   - Incremental sync and rebuild libsigrokdecode"
	@echo "  clean-libsigrokdecode    - Clean libsigrokdecode build files"
	@echo ""
	@echo "  configure-pulseview      - Configure PulseView"
	@echo "  build-pulseview          - Build PulseView"
	@echo "  install-pulseview        - Install PulseView"
	@echo "  update-pulseview         - Incremental sync and rebuild PulseView"
	@echo "  clean-pulseview          - Clean PulseView build files"
	@echo ""
	@echo "  configure-slogicview     - Configure SLogicView"
	@echo "  build-slogicview         - Build SLogicView"
	@echo "  install-slogicview       - Install SLogicView"
	@echo "  update-slogicview        - Incremental sync and rebuild SLogicView"
	@echo "  clean-slogicview         - Clean SLogicView build files"
	@echo ""
	@echo "  configure-sigrok-cli     - Configure sigrok-cli"
	@echo "  build-sigrok-cli         - Build sigrok-cli"
	@echo "  install-sigrok-cli       - Install sigrok-cli"
	@echo "  update-sigrok-cli        - Incremental sync and rebuild sigrok-cli"
	@echo "  clean-sigrok-cli         - Clean sigrok-cli build files"
	@echo ""

.PHONY: all prepare build install run appimage clean distclean help \
	configure-libsigrok build-libsigrok install-libsigrok update-libsigrok clean-libsigrok \
	configure-libsigrokdecode build-libsigrokdecode install-libsigrokdecode update-libsigrokdecode clean-libsigrokdecode \
	install-sigrok-dependencies \
	configure-pulseview build-pulseview install-pulseview update-pulseview clean-pulseview \
	configure-slogicview build-slogicview install-slogicview update-slogicview clean-slogicview \
	configure-sigrok-cli build-sigrok-cli install-sigrok-cli update-sigrok-cli clean-sigrok-cli \
	configure-sigrok-bridge build-sigrok-bridge install-sigrok-bridge clean-sigrok-bridge \
	configure-ngscopeclient build-ngscopeclient install-ngscopeclient clean-ngscopeclient
