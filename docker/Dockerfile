# syntax=docker/dockerfile:1.7
ARG BASE_IMAGE=ubuntu:24.04@sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517
FROM ${BASE_IMAGE}

ARG CANN_INSTALLER=Ascend-cann-toolkit_9.2.0-beta.2_linux-x86_64.run
ARG CANN_SHA256
ARG ACCEPT_CANN_EULA=no

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    ASCEND_CACHE_PATH=/workspace/.cache/ascend

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        bash build-essential ca-certificates ccache cmake curl gdb git ninja-build python3 python3-pip python3-venv unzip && \
    rm -rf /var/lib/apt/lists/*

COPY downloads/${CANN_INSTALLER} /tmp/cann.run
RUN test "${ACCEPT_CANN_EULA}" = "yes" || \
        (printf '%s\n' 'Build refused: pass --accept-eula after reviewing the CANN Software User License Agreement 2.0.' >&2; exit 2) && \
    printf '%s  %s\n' "${CANN_SHA256}" /tmp/cann.run | sha256sum -c - && \
    chmod 0555 /tmp/cann.run && \
    (/tmp/cann.run --quiet --full --install-path=/usr/local/Ascend --install-for-all || \
        (status=$?; tail -n 200 /var/log/ascend_seclog/ascend_toolkit_install.log >&2; exit "${status}")) && \
    rm -f /tmp/cann.run && \
    test -f /usr/local/Ascend/cann/set_env.sh

COPY docker/entrypoint.sh /usr/local/bin/ascendc-entrypoint
RUN chmod 0555 /usr/local/bin/ascendc-entrypoint

WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/ascendc-entrypoint"]
CMD ["bash"]
