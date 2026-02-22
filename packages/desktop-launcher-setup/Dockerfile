# Build Windows 3D Linker setup EXE using Inno Setup (Wine) on Linux.
# Use BuildKit and --output to extract the EXE directly (no docker run):
#   DOCKER_BUILDKIT=1 docker build -f packages/desktop-launcher-setup/Dockerfile \
#     --output type=local,dest=packages/desktop-launcher-setup/dist \
#     packages/desktop-launcher-setup
# Then packages/desktop-launcher-setup/dist/3d_setup.exe will exist.
FROM amake/innosetup AS builder
COPY setup.iss /work/
WORKDIR /work
RUN iscc setup.iss

# Minimal stage: only the EXE, so --output extracts just that.
FROM scratch
COPY --from=builder /work/dist/3d_setup.exe /3d_setup.exe
