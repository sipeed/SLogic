FROM debian:13-slim

ENV DEBIAN_FRONTEND=noninteractive

# Toolchain + libsigrok-sys C build deps (sigrok-bridge) and the ngscopeclient
# Vulkan/GLFW/shader stack. glibc target (Debian trixie, glibc 2.41): unlike
# the musl-Alpine target, this validates the Vulkan GUI and glibc-only runtime.
# trixie's apt meson (1.7) is new enough to build glib 2.80 (needs >= 1.2).
RUN apt-get update && apt-get install -y --no-install-recommends \
        bash \
        build-essential \
        ccache \
        autoconf \
        automake \
        libtool \
        pkg-config \
        cmake \
        ninja-build \
        meson \
        python3 \
        python3-pip \
        python3-packaging \
        make \
        curl \
        ca-certificates \
        tar \
        bzip2 \
        xz-utils \
        sed \
        git \
        rsync \
        file \
        patchelf \
        squashfs-tools \
        desktop-file-utils \
        libvulkan-dev \
        vulkan-tools \
        libglfw3-dev \
        libyaml-cpp-dev \
        libsigc++-3.0-dev \
        glslang-tools \
        glslang-dev \
        spirv-tools \
        spirv-headers \
        libshaderc-dev \
        libhidapi-dev \
        libfftw3-dev \
        catch2 \
        libomp-dev \
        libglm-dev \
        libgtk-3-dev \
    && rm -rf /var/lib/apt/lists/*

# linuxdeploy + its appimage output plugin for the ngscopeclient AppImage.
# Baked into the image so the ensure-environment content hash caches them; run
# with APPIMAGE_EXTRACT_AND_RUN=1 (no FUSE in the container). The plugin must be
# on PATH for `linuxdeploy --output appimage` to find it.
RUN curl --fail --location --retry 3 \
        https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage \
        --output /usr/local/bin/linuxdeploy \
    && curl --fail --location --retry 3 \
        https://github.com/linuxdeploy/linuxdeploy-plugin-appimage/releases/download/continuous/linuxdeploy-plugin-appimage-x86_64.AppImage \
        --output /usr/local/bin/linuxdeploy-plugin-appimage \
    && chmod +x /usr/local/bin/linuxdeploy /usr/local/bin/linuxdeploy-plugin-appimage

# Rust via rustup (Debian's cargo is too old for libsigrok-sys). Installed to a
# fixed system prefix that stays CARGO_HOME at build and run time, so the cargo
# and rustc proxies remain on PATH; the crate registry is mounted at run time.
ENV RUSTUP_HOME=/opt/rust/rustup \
    CARGO_HOME=/opt/rust/cargo \
    PATH=/opt/rust/cargo/bin:/usr/local/bin:$PATH
RUN curl --proto '=https' --tlsv1.2 --fail --location --retry 3 https://sh.rustup.rs \
        | sh -s -- -y --profile minimal --default-toolchain stable \
    && chmod -R a+rwX /opt/rust

WORKDIR /workspace
