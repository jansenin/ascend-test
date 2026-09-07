.PHONY: image shell cpu-2201 cpu-3510 sim-2201 sim-3510 test-cpu-2201 test-cpu-3510

image:
	./scripts/docker-build.sh --accept-eula

shell:
	./scripts/docker-run.sh bash

cpu-2201:
	./scripts/docker-run.sh ./scripts/build.sh cpu dav-2201

cpu-3510:
	./scripts/docker-run.sh ./scripts/build.sh cpu dav-3510

sim-2201:
	./scripts/docker-run.sh ./scripts/build.sh sim dav-2201

sim-3510:
	./scripts/docker-run.sh ./scripts/build.sh sim dav-3510

test-cpu-2201:
	./scripts/docker-run.sh ./scripts/test.sh cpu dav-2201

test-cpu-3510:
	./scripts/docker-run.sh ./scripts/test.sh cpu dav-3510
