"""Cancellable image pull client; parent process imposes the wall-clock deadline."""

import sys

import docker

if __name__ == "__main__":
    client = docker.from_env(timeout=20)
    try:
        client.images.pull(sys.argv[1])
    finally:
        client.close()
