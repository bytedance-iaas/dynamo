#! /bin/bash

set -ex

# 打包时必填字段: CUSTOM_VLLM_REF, CUSTOM_VLLM_WHEEL_REPO, CUSTOM_DOCKER_USERNAME, CUSTOM_DOCKER_PASSWORD

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

TARGET="runtime"
IMAGE_REPO_NAME="dynamo"

if [ "${CUSTOM_BUILD_WHEEL_ONLY}" == "true" ]; then
    # 如果 CUSTOM_BUILD_WHEEL_ONLY 为 true，则只构建 wheelhouse 镜像，并随后上传到 tos
    TARGET="wheel_builder"
    IMAGE_REPO_NAME="wheelhouse"
fi

# IMAGE_NAME 格式：dynamo:v0.8.5.byted.0.0.2.202505152017
IMAGE_TAG=$(echo v${VLLM_REF#v} | sed 's/+/./g')
IMAGE_TAG=$(echo "$IMAGE_TAG" | sed "s/\(.*\.\)[0-9]\+/\1$BUILD_TIME/")  # 替换为当前时戳
IMAGE_NAME=${IMAGE_REPO_NAME}:${IMAGE_TAG}
TARGET_IMAGE=hub.byted.org/iaas/${IMAGE_NAME}

# 如果是 SCM 构建，则准备 docker 环境
if [[ "${SCM_BUILD}" == "True" ]]; then
    source /root/start_dockerd.sh
fi

if [ "${CUSTOM_BUILD_WHEEL_ONLY}" == "true" ]; then
    # tos 相关参数，必须设置
    if [ -z "$CUSTOM_TOS_AK" ] && [ -z "$CUSTOM_TOS_SK" ]; then
        echo "CUSTOM_TOS_AK and CUSTOM_TOS_SK are not set"
        exit 1
    fi
    if [ -z "$CUSTOM_TOS_BUCKET" ]; then
        echo "CUSTOM_TOS_BUCKET is not set"
        exit 1
    fi
else
    # 默认构建 runtime 镜像，并随后 push 到 cr
    # docker push username/password，必须设置
    if [ -z "${CUSTOM_DOCKER_USERNAME}" ] || [ -z "${CUSTOM_DOCKER_PASSWORD}" ]; then
        echo "CUSTOM_DOCKER_USERNAME or CUSTOM_DOCKER_PASSWORD is not set"
        exit 1
    fi
    # 检查 IMAGE_TAG，应当包含 .byted 字符串
    if [[ "${IMAGE_TAG}" != *".byted"* ]]; then
        echo "IMAGE_TAG must contain .byted string, please check CUSTOM_VLLM_REF env"
        exit 1
    fi

    skopeo login -u ${CUSTOM_DOCKER_USERNAME} -p ${CUSTOM_DOCKER_PASSWORD} ${TARGET_IMAGE%%/*}
fi

cd container

sed -i 's|docker build -f|docker build --network=host -f|' ./build_submodule.sh
sed -i 's|VLLM_BASE_IMAGE="nvcr.io/nvidia/cuda-dl-base"|VLLM_BASE_IMAGE="iaas-gpu-cn-beijing.cr.volces.com/nvcr.io/nvidia/cuda-dl-base"|' ./build_submodule.sh
sed -i 's|ARG BASE_IMAGE="nvcr.io/nvidia/cuda-dl-base"|ARG BASE_IMAGE="iaas-gpu-cn-beijing.cr.volces.com/nvcr.io/nvidia/cuda-dl-base"|' ./Dockerfile.vllm.submodule
sed -i 's|ARG RUNTIME_IMAGE="nvcr.io/nvidia/cuda"|ARG RUNTIME_IMAGE="iaas-gpu-cn-beijing.cr.volces.com/nvcr.io/nvidia/cuda"|' ./Dockerfile.vllm.submodule
# 由于 ubuntu 官方源不稳定，使用 byted 源 
sed -i 's@RUN apt-get update@RUN sed -i "s|http://archive.ubuntu.com|http://mirrors.byted.org|g" /etc/apt/sources.list.d/ubuntu.sources ; sed -i "s|http://security.ubuntu.com|http://mirrors.byted.org|g" /etc/apt/sources.list.d/ubuntu.sources ; apt-get update@' ./Dockerfile.vllm.submodule
sed -i 's@RUN apt update@RUN sed -i "s|http://archive.ubuntu.com|http://mirrors.byted.org|g" /etc/apt/sources.list.d/ubuntu.sources ; sed -i "s|http://security.ubuntu.com|http://mirrors.byted.org|g" /etc/apt/sources.list.d/ubuntu.sources ; apt update@' ./Dockerfile.vllm.submodule

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

# 构建 submodule 或 wheelhouse， 取决于 CUSTOM_BUILD_WHEEL_ONLY 是否为 true
./build_submodule.sh ${hpkv_version_arg} --build-arg VLLM_PATCHED_PACKAGE_NAME=vllm --build-arg VLLM_WHEEL_REPO=${VLLM_WHEEL_REPO} --build-arg VLLM_REF=${VLLM_REF} --build-arg VLLM_PATCHED_PACKAGE_VERSION=${VLLM_VERSION} ${proxy_args} --build-arg CARGO_BUILD_JOBS=$(nproc) ${target_args} --tag ${IMAGE_NAME}

mkdir -p ${OUTPUT_DIR}

if [ "${CUSTOM_BUILD_WHEEL_ONLY}" == "true" ]; then
    echo "Build wheelhouse image ${IMAGE_NAME} successfully"
    docker run --rm -v ${OUTPUT_DIR}:${OUTPUT_DIR} ${IMAGE_NAME} bash -c 'ls /workspace/dist && for file in $(find /workspace/dist -name "ai_dynamo*.whl"); do cp -v $file '"${OUTPUT_DIR}"'; done'
    echo "Upload wheels to tos"
    TOS_UTIL_URL=https://tos-tools.tos-cn-beijing.volces.com/linux/amd64/tosutil
    if [ ! -z "$CUSTOM_TOS_UTIL_URL" ]; then
        TOS_UTIL_URL=$CUSTOM_TOS_UTIL_URL
    fi
    wget $TOS_UTIL_URL -O tosutil && chmod +x tosutil
    for wheel_file in $(find $OUTPUT_DIR -name "*.whl"); do
        echo "uploading $wheel_file to tos..."
        ./tosutil cp $wheel_file tos://${CUSTOM_TOS_BUCKET}/packages/$(basename $wheel_file) -re cn-beijing -e tos-cn-beijing.volces.com -i $CUSTOM_TOS_AK -k $CUSTOM_TOS_SK
    done
    echo "Upload wheels to tos successfully"
else
    docker images
    http_proxy= https_proxy= HTTP_PROXY= HTTPS_PROXY= skopeo copy --insecure-policy --all --retry-times 10 docker-daemon:$IMAGE_NAME docker://$TARGET_IMAGE

    echo "Build and push ${TARGET_IMAGE} successfully"
    cd ${ROOT_DIR}
    echo ${TARGET_IMAGE} > ${OUTPUT_DIR}/image_name
fi
