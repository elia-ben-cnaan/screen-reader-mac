#!/bin/bash
cd "$(dirname "$0")"; [ -d ScreenReader.app ] || ./build.sh; open ScreenReader.app
