#! /bin/bash

set -ex

ROOT_DIR=$(pwd)
OUTPUT_DIR=${ROOT_DIR}/output
BYTED_MIRROR="mirrors.byted.org"

cd container

required_env_vars=(CUSTOM_TRTLLM_COMMIT CUSTOM_IMAGE_TAG CUSTOM_DOCKER_USERNAME CUSTOM_DOCKER_PASSWORD)
for env_var in "${required_env_vars[@]}"; do
    if [ -z "${!env_var}" ]; then
        echo "${env_var} is not set"
        exit 1
    fi
done

IMAGE_TAG=${CUSTOM_IMAGE_TAG}
IMAGE_REPO_NAME="dynamo-trtllm"
IMAGE_NAME=${IMAGE_REPO_NAME}:${IMAGE_TAG}
TARGET_IMAGE=hub.byted.org/iaas/${IMAGE_NAME}

skopeo login -u ${CUSTOM_DOCKER_USERNAME} -p ${CUSTOM_DOCKER_PASSWORD} ${TARGET_IMAGE%%/*}

export no_proxy=$no_proxy,${BYTED_MIRROR}
proxy_args=""
for var in http_proxy https_proxy no_proxy; do
    [ ! -z "${!var}" ] && proxy_args="$proxy_args --build-arg $var=${!var}"
done

# 如果是 SCM 构建，则准备 docker 环境
if [[ "${SCM_BUILD}" == "True" ]]; then
    source /root/start_dockerd.sh
fi

sed -i "s@make -C docker wheel_build@sed -i \"s|docker build |docker build $proxy_args |g\" docker/Makefile; make -C docker wheel_build@" build_trtllm_wheel.sh
sed -i "s@make -C docker wheel_build@sed -i \"s|docker buildx build |docker buildx build $proxy_args --network host |g\" docker/Makefile; make -C docker wheel_build@" build_trtllm_wheel.sh
sed -i "s@make -C docker wheel_build@sed -i \"s|=nvcr.io/nvidia/|=iaas-gpu-cn-beijing.cr.volces.com/nvcr.io/nvidia/|\" ./docker/Dockerfile.multi; make -C docker wheel_build@" build_trtllm_wheel.sh
sed -i "s@make -C docker wheel_build@sed -i \"s|RUN bash|RUN sed -i 's_http://archive.ubuntu.com_http://${BYTED_MIRROR}_g' /etc/apt/sources.list.d/ubuntu.sources ; sed -i 's_http://security.ubuntu.com_http://${BYTED_MIRROR}_g' /etc/apt/sources.list.d/ubuntu.sources ; http_proxy=$http_proxy https_proxy=$https_proxy no_proxy=$no_proxy bash|\" ./docker/Dockerfile.multi; make -C docker wheel_build@" build_trtllm_wheel.sh
sed -i "s@make -C docker wheel_build@sed -i \"s|RUN bash|RUN http_proxy=$http_proxy https_proxy=$https_proxy no_proxy=$no_proxy bash|\" ./docker/Dockerfile.multi; make -C docker wheel_build@" build_trtllm_wheel.sh
sed -i "s@env -i@env -i http_proxy=$http_proxy https_proxy=$https_proxy no_proxy=$no_proxy@g" build.sh
sed -i "s@docker build @docker build --network host @g" build.sh

wheel_dir=${ROOT_DIR}/trtllm_wheel
mkdir -p ${wheel_dir}

# 开始构建
./build.sh ${proxy_args} --framework TENSORRTLLM --tensorrtllm-commit ${CUSTOM_TRTLLM_COMMIT} --tensorrtllm-pip-wheel-dir ${wheel_dir} --tag ${IMAGE_NAME}

mkdir -p ${OUTPUT_DIR}
cp -r ${wheel_dir}/*.whl ${OUTPUT_DIR}

docker images
http_proxy= https_proxy= HTTP_PROXY= HTTPS_PROXY= skopeo copy --insecure-policy --all --retry-times 10 docker-daemon:$IMAGE_NAME docker://$TARGET_IMAGE

echo "Build and push ${TARGET_IMAGE} successfully"
cd ${ROOT_DIR}
echo ${TARGET_IMAGE} > ${OUTPUT_DIR}/image_name

