#! /bin/bash

set -ex

# 打包时必填字段: CUSTOM_VLLM_REF, CUSTOM_VLLM_WHEEL_REPO, CUSTOM_TARGET, CUSTOM_DOCKER_USERNAME, CUSTOM_DOCKER_PASSWORD

ROOT_DIR=$(pwd)
OUTPUT_DIR=${ROOT_DIR}/output
BUILD_TIME=$(date +%Y%m%d%H%M)

if [ -z "${CUSTOM_VLLM_REF}" ]; then
    echo "CUSTOM_VLLM_REF is not set"
    exit 1
fi
VLLM_REF=${CUSTOM_VLLM_REF}


VLLM_VERSION=${VLLM_REF}
VLLM_VERSION=${VLLM_VERSION#v}

if [ ! -z "${CUSTOM_VLLM_VERSION}" ]; then
    VLLM_VERSION=${CUSTOM_VLLM_VERSION}
fi

VLLM_WHEEL_REPO=""
if [ -z "${CUSTOM_VLLM_WHEEL_REPO}" ]; then
    echo "CUSTOM_VLLM_WHEEL_REPO is not set"
    exit 1
fi
VLLM_WHEEL_REPO=${CUSTOM_VLLM_WHEEL_REPO}

TARGET=""
if [ ! -z "${CUSTOM_TARGET}" ]; then
    TARGET=${CUSTOM_TARGET}
fi

# IMAGE_NAME 格式：dynamo:v0.8.5.byted.0.0.2.202505152017
IMAGE_TAG=$(echo v${VLLM_REF#v} | sed 's/+/./g')
IMAGE_TAG=$(echo "$IMAGE_TAG" | sed "s/\(.*\.\)[0-9]\+/\1$BUILD_TIME/")  # 替换为当前时戳
IMAGE_NAME=dynamo:${IMAGE_TAG}
TARGET_IMAGE=iaas-gpu-cn-beijing.cr.volces.com/serving/dynamo:${IMAGE_TAG}

# 检查 IMAGE_TAG，应当包含 .byted 字符串
if [[ "${IMAGE_TAG}" != *".byted"* ]]; then
    echo "IMAGE_TAG must contain .byted string, please check CUSTOM_VLLM_REF env"
    exit 1
fi

# docker push username/password，必须设置
if [ -z "${CUSTOM_DOCKER_USERNAME}" ] || [ -z "${CUSTOM_DOCKER_PASSWORD}" ]; then
    echo "CUSTOM_DOCKER_USERNAME or CUSTOM_DOCKER_PASSWORD is not set"
    exit 1
fi

docker login -u ${CUSTOM_DOCKER_USERNAME} -p ${CUSTOM_DOCKER_PASSWORD} iaas-gpu-cn-beijing.cr.volces.com

# 如果是 SCM 构建，则准备 docker 环境
if [[ "${SCM_BUILD}" == "True" ]]; then
    source /root/start_dockerd.sh
fi

cd container

sed -i 's|docker build -f|docker build --network=host -f|' ./build_submodule.sh
sed -i 's|VLLM_BASE_IMAGE="nvcr.io/nvidia/cuda-dl-base"|VLLM_BASE_IMAGE="iaas-gpu-cn-beijing.cr.volces.com/nvcr.io/nvidia/cuda-dl-base"|' ./build_submodule.sh
sed -i 's|ARG BASE_IMAGE="nvcr.io/nvidia/cuda-dl-base"|ARG BASE_IMAGE="iaas-gpu-cn-beijing.cr.volces.com/nvcr.io/nvidia/cuda-dl-base"|' ./Dockerfile.vllm.submodule
sed -i 's|ARG RUNTIME_IMAGE="nvcr.io/nvidia/cuda"|ARG RUNTIME_IMAGE="iaas-gpu-cn-beijing.cr.volces.com/nvcr.io/nvidia/cuda"|' ./Dockerfile.vllm.submodule

proxy_args=""
if [ ! -z "$http_proxy" ]; then
    proxy_args="$proxy_args --build-arg http_proxy=$http_proxy"
fi
if [ ! -z "$https_proxy" ]; then
    proxy_args="$proxy_args --build-arg https_proxy=$https_proxy"
fi
if [ ! -z "$no_proxy" ]; then
    proxy_args="$proxy_args --build-arg no_proxy=$no_proxy"
fi

target_args=""
if [ ! -z "${TARGET}" ]; then
    target_args="--target ${TARGET}"
fi

hpkv_version_arg=""
if [ ! -z "${CUSTOM_HPKV_VERSION}" ]; then
    hpkv_version_arg="--build-arg HPKV_VERSION=${CUSTOM_HPKV_VERSION}"
fi

# 构建 submodule
./build_submodule.sh ${hpkv_version_arg} --build-arg VLLM_PATCHED_PACKAGE_NAME=vllm --build-arg VLLM_WHEEL_REPO=${VLLM_WHEEL_REPO} --build-arg VLLM_REF=${VLLM_REF} --build-arg VLLM_PATCHED_PACKAGE_VERSION=${VLLM_VERSION} ${proxy_args} --build-arg CARGO_BUILD_JOBS=$(nproc) ${target_args} --tag ${IMAGE_NAME}

docker images
docker tag ${IMAGE_NAME} ${TARGET_IMAGE}
docker push ${TARGET_IMAGE}

echo "Build and push ${TARGET_IMAGE} successfully"

cd ${ROOT_DIR}
mkdir -p ${OUTPUT_DIR}
echo ${TARGET_IMAGE} > ${OUTPUT_DIR}/image_name
