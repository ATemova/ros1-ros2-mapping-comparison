# One-command entry points. Everything runs in Docker; results land in results/raw/,
# reports in results/reports/<TAG>/ and results/report.md.
#
#   make experiment STACK=ros2 ALGO=slam_toolbox RUNS=5 BAG=data/bags/corridor_01.bag
#   make matrix  BAG=...                 ROS1 vs ROS2 (Humble, Fast DDS)
#   make rmw     BAG=... DISTRO=humble   Fast DDS vs Cyclone DDS vs Zenoh
#   make distros BAG=...                 Humble vs Jazzy
#   make stress  BAG=... CPUS=1 MEMORY=2g [VARIANTS="ros1 ros2"]
#   make long                            30-min synthetic loop bag, memory growth
#   make report  TAG=<run_tag> [GROUP_BY=rmw]
#   make sample-size TAG=<pilot_tag> [GROUP_BY=stack]   runs needed per comparison
#   make pull VERSION=v0.3.0             use the published images of a release
#   make lock                            pin base images by digest
#   make check                           unit tests + lint + parameter/schema checks
# `make help` lists every target and variable.

SHELL := /bin/bash
.DEFAULT_GOAL := help

STACK     ?= ros2
DISTRO    ?= humble
RMW       ?= fastrtps
ALGO      ?= slam_toolbox
RUNS      ?= 5
RATE      ?= 1.0
BAG       ?= data/bags/synthetic.bag
PYTHON    ?= python3
ifeq ($(origin TAG), undefined)
TAG := $(shell date +%Y%m%d_%H%M%S)
endif

ifeq ($(STACK),ros1)
VARIANT := ros1
else
VARIANT := ros2:$(DISTRO):$(RMW)
endif

# passed to experiments/run_matrix.sh when set
export ALGO RUNS RATE SETTLE COOLDOWN CPUS CPU_SET MEMORY CONDITION DOCKER_ARGS BUILD

MATRIX = BAG="$(BAG)" RUN_TAG="$(TAG)" ./experiments/run_matrix.sh

IMAGE_REPO ?= ghcr.io/atemova/ros1-ros2-mapping-comparison

.PHONY: help images image-ros1 image-ros2 synthetic experiment matrix rmw distros stress long \
        report sample-size test lint check sample-bag dataset lock pull validate

help:  ## show this help
	@grep -hE '^[a-z0-9_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[1m%-12s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "Variables: STACK=$(STACK) DISTRO=$(DISTRO) RMW=$(RMW) ALGO=$(ALGO) RUNS=$(RUNS) RATE=$(RATE)"
	@echo "           BAG=$(BAG) TAG=<timestamp>  stress: CPUS CPU_SET MEMORY CONDITION"

images: image-ros1 image-ros2  ## build ros1-mapping:noetic and ros2-mapping:<DISTRO> (host arch)

image-ros1:  ## build the ROS1 Noetic image
	docker/build.sh ros1 noetic

image-ros2:  ## build the ROS2 image for DISTRO (humble, jazzy)
	docker/build.sh ros2 $(DISTRO)

lock:  ## pin ros:noetic/humble/jazzy by digest in docker/base-images.lock (commit it)
	docker/lock.sh update

pull:  ## pull a release's published images (VERSION=v0.3.0) and tag them for local use
	@[ -n "$(VERSION)" ] || { echo "set VERSION, e.g. make pull VERSION=v0.3.0"; exit 1; }
	@for img in ros1-noetic ros2-humble ros2-jazzy; do \
	  stack=$${img%%-*}; distro=$${img#*-}; \
	  docker pull "$(IMAGE_REPO):$$img-$(VERSION)" && \
	  docker tag "$(IMAGE_REPO):$$img-$(VERSION)" "$$stack-mapping:$$distro" || exit 1; \
	done; echo "Tagged ros1-mapping:noetic, ros2-mapping:humble, ros2-mapping:jazzy from $(VERSION)"

synthetic: image-ros2  ## generate data/bags/synthetic.bag (+ ROS2 form, ground truth, floor plan)
	@if [ ! -f data/bags/synthetic.bag ]; then \
	  docker run --rm --user "$$(id -u):$$(id -g)" -v "$$PWD":/work -w /work ros2-mapping:$(DISTRO) \
	    bash -c "python3 experiments/make_synthetic_bag.py && ./experiments/convert_bag.sh data/bags/synthetic.bag"; \
	else echo "data/bags/synthetic.bag exists"; fi

experiment:  ## RUNS runs of one variant: STACK=ros1|ros2 [DISTRO RMW] BAG=...
	VARIANTS="$(VARIANT)" $(MATRIX)

matrix:  ## ROS1 vs ROS2 (DISTRO, Fast DDS), counterbalanced
	VARIANTS="ros1 ros2:$(DISTRO):fastrtps" GROUP_BY=stack $(MATRIX)

rmw:  ## Fast DDS vs Cyclone DDS vs Zenoh on ROS2 DISTRO
	VARIANTS="ros2:$(DISTRO):fastrtps ros2:$(DISTRO):cyclonedds ros2:$(DISTRO):zenoh" GROUP_BY=rmw $(MATRIX)

distros:  ## Humble vs Jazzy with one RMW (RMW=...)
	VARIANTS="ros2:humble:$(RMW) ros2:jazzy:$(RMW)" GROUP_BY=ros_distro $(MATRIX)

stress:  ## a matrix under CPU/memory limits: CPUS=1 or CPU_SET=0 and/or MEMORY=2g
	@if [ -z "$(CPUS)$(CPU_SET)$(MEMORY)$(filter-out 1.0,$(RATE))" ]; then \
	  echo "set CPUS, CPU_SET, MEMORY and/or RATE (e.g. make stress CPUS=1 BAG=...)"; exit 1; fi
	VARIANTS="$(or $(VARIANTS),ros1 ros2:$(DISTRO):fastrtps)" $(MATRIX)

long: image-ros2  ## 30-min synthetic loop bag, RUNS=3 per stack (memory growth)
	@if [ ! -f data/bags/long30.bag ]; then \
	  docker run --rm --user "$$(id -u):$$(id -g)" -v "$$PWD":/work -w /work ros2-mapping:$(DISTRO) \
	    bash -c "python3 experiments/make_synthetic_bag.py --out data/bags/long30.bag --path loop --duration 1800 \
	      && ./experiments/convert_bag.sh data/bags/long30.bag"; fi
	VARIANTS="$(or $(VARIANTS),ros1 ros2:$(DISTRO):fastrtps)" RUNS=$(if $(filter command line,$(origin RUNS)),$(RUNS),3) \
	  BAG=data/bags/long30.bag RUN_TAG="$(TAG)" ./experiments/run_matrix.sh

report:  ## regenerate results/reports/TAG/report.md and results/report.md [GROUP_BY=...]
	docker run --rm --user "$$(id -u):$$(id -g)" -v "$$PWD":/work -w /work ros2-mapping:humble \
	  python3 metrics/make_report.py --tag "$(TAG)" --group-by "$(or $(GROUP_BY),stack)" \
	    $(if $(BASELINE),--baseline "$(BASELINE)") --out "results/reports/$(TAG)" --latest results/report.md

sample-size:  ## runs needed per comparison, from pilot runs: TAG=<pilot> [GROUP_BY=stack] [POWER=0.8]
	$(PYTHON) metrics/sample_size.py --tag "$(TAG)" --group-by "$(or $(GROUP_BY),stack)" \
	  --power "$(or $(POWER),0.8)" $(if $(BASELINE),--baseline "$(BASELINE)")

validate:  ## check every run folder in results/raw against the schemas
	$(PYTHON) experiments/validate_runs.py results/raw

test:  ## unit tests (host Python with numpy)
	$(PYTHON) -m unittest discover -s tests

lint:  ## shellcheck + parameter/mapping-table and schema checks
	shellcheck --severity=warning experiments/*.sh docker/*.sh
	$(PYTHON) experiments/check_params.py --check-doc
	$(PYTHON) experiments/validate_runs.py --self-test

check: test lint  ## everything CI checks without ROS

sample-bag:  ## cut a short sample from BAG for CI / release assets (SECONDS=30)
	$(PYTHON) experiments/cut_bag.py "$(BAG)" --seconds $(or $(SECONDS),30) --out data/bags/sample.bag

dataset:  ## package bags + references + results for Zenodo (NAME=..., BAGS="...")
	./experiments/package_dataset.sh "$(or $(NAME),ros1-ros2-mapping-dataset)" $(or $(BAGS),$(BAG))
