#!/bin/bash
JDK=/home/eh6/E128356/.local/lib/local-jdk/jdk-24.0.2
JAR=/scratch/fast/kun/projects/trec-rag-26/tasks/bm25_index/jars/anserini-2.2.0-fatjar.jar
IDX=/scratch/fast/kun/projects/trec-rag-26/data/built-indexes/climbmix-bm25
cd /scratch/fast/kun/projects/trec-rag-26/tasks/bm25_index/boolsearch
# Cap heap so a per-call BoolSearch JVM can't balloon (it just mmap-opens the
# index + runs one query); keeps it a good RAM citizen alongside the SSR and
# dense servers. Override with BS_XMX (default 4g).
"$JDK/bin/java" -Xmx"${BS_XMX:-4g}" -cp ".:$JAR" BoolSearch "$IDX" "$1" "$2" "${3:-200}" 2>/dev/null
