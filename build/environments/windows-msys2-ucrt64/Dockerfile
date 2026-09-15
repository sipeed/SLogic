FROM ghcr.io/msys2/msys2-docker-experimental

# Use TUNA mirror for faster downloads
RUN /usr/bin/msys2 -c "sed -i 's|Server = https://repo.msys2.org/|Server = https://mirrors.tuna.tsinghua.edu.cn/msys2/|g' /etc/pacman.d/mirrorlist* && \
    sed -i 's|Server = https://mirror.msys2.org/|Server = https://mirrors.tuna.tsinghua.edu.cn/msys2/|g' /etc/pacman.d/mirrorlist*"

# An MSYS2 runtime upgrade terminates every running MSYS2 process. Keep the
# outer Linux shell alive so Docker can commit that first upgrade layer.
RUN /usr/bin/msys2 -c "pacman -Syu --noconfirm" || true
RUN /usr/bin/msys2 -c "pacman -Syu --noconfirm"

# Install build dependencies in UCRT64 environment
RUN /usr/bin/msys2 -c "pacman -S --noconfirm --needed \
        autoconf \
        automake \
        libtool \
        make \
        rsync \
        zip \
        mingw-w64-ucrt-x86_64-toolchain \
        mingw-w64-ucrt-x86_64-ccache \
        mingw-w64-ucrt-x86_64-cmake \
        mingw-w64-ucrt-x86_64-pkg-config \
        mingw-w64-ucrt-x86_64-glib2 \
        mingw-w64-ucrt-x86_64-glibmm-2.68 \
        mingw-w64-ucrt-x86_64-libusb \
        mingw-w64-ucrt-x86_64-libzip \
        mingw-w64-ucrt-x86_64-libserialport \
        mingw-w64-ucrt-x86_64-libftdi \
        mingw-w64-ucrt-x86_64-hidapi \
        mingw-w64-ucrt-x86_64-nettle \
        mingw-w64-ucrt-x86_64-boost \
        mingw-w64-ucrt-x86_64-qt6-base \
        mingw-w64-ucrt-x86_64-qt6-svg \
        mingw-w64-ucrt-x86_64-qt6-tools \
        mingw-w64-ucrt-x86_64-python \
        mingw-w64-ucrt-x86_64-doxygen \
        mingw-w64-ucrt-x86_64-swig \
    && pacman -Scc --noconfirm"

# Kept separate so adding/changing the single-file packager does not
# invalidate the expensive compiler and Qt dependency layer above.
RUN /usr/bin/msys2 -c "pacman -S --noconfirm --needed \
        mingw-w64-ucrt-x86_64-7zip \
        mingw-w64-ucrt-x86_64-nsis \
    && pacman -Scc --noconfirm"
