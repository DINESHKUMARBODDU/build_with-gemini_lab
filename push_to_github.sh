#!/usr/bin/env bash
set -e
git init
git add .
git commit -m "DataPilot: data Q&A agent with Gemini, charts and tests"
git branch -M main
git remote add origin https://github.com/DINESHKUMARBODDU/build_with-gemini_lab.git
git push -u origin main
