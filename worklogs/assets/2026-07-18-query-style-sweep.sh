#!/bin/zsh
# Query-style x engine sweep. Output: compact per-run blocks.
cd /Users/kun/Projects/rmit/research/trec-rag-26

run() {  # run <task_id> <style_id> <query>
  local tid="$1" sid="$2" q="$3"
  for eng in search_semantic search_keyword search_fusion; do
    echo "=== ${tid} ${sid} [${eng}] Q: ${q}"
    uv run --group aus-agent python src/tools/search_tool.py "$q" --k 5 --engine "$eng" --max-chars 170 2>/dev/null \
      | jq -r '.results[] | "\(.rank)|\(.rrf_score)|\(.text | gsub("\n"; " "))"'
  done
}

# T1 broad survey (UBI, topic 28)
run T1 nlq  "What are the arguments for and against universal basic income?"
run T1 kw   "universal basic income effects debate"
run T1 bad  "income"

# T2 named program (Finland UBI pilot, topic 28)
run T2 nlq  "What were the results of Finland's basic income experiment?"
run T2 kw   "Finland basic income experiment results"
run T2 ent  "Kela basic income trial Finland"
run T2 bad  "peer-reviewed economic studies policy analysis commentary UBI programs developed countries"

# T3 definitional/conceptual (predictive coding, topic 2)
run T3 nlq  "What is predictive coding in neuroscience?"
run T3 kw   "predictive coding brain perception theory"
run T3 ent  "predictive coding Karl Friston free energy principle"

# T4 comparative (RISC vs CISC, topic 14)
run T4 nlq  "What is the difference between RISC and CISC instruction set architectures?"
run T4 kw   "RISC CISC comparison instruction set"
run T4 ent  "RISC vs CISC"

# T5 numeric/statistical evidence (Finland UBI employment stats, topic 28)
run T5 nlq  "How much did employment change for participants in Finland's basic income trial?"
run T5 kw   "Finland basic income trial employment days effect"
run T5 ent  "Finland basic income 560 euros employment"

# T6 rare technical term (vanishing gradient, topic 9)
run T6 nlq  "Why do recurrent neural networks suffer from the vanishing gradient problem?"
run T6 kw   "vanishing gradient problem RNN"
run T6 ent  "vanishing gradient Hochreiter"

# T7 named person (LSTM inventors, topic 9)
run T7 nlq  "Who invented the LSTM neural network architecture?"
run T7 kw   "Hochreiter Schmidhuber LSTM 1997"
run T7 ent  "Sepp Hochreiter long short-term memory"
run T7 bad  "comprehensive expository analysis key AI architectures historical development"

# T8 common-word ambiguous (preschool sharing tantrums, topic 7)
run T8 nlq  "How can teachers help a preschooler who refuses to share and has tantrums?"
run T8 kw   "preschool sharing tantrum behavior strategies"
run T8 bad  "sharing"

# T9 named product (CS:GO, topic 17)
run T9 nlq  "Why has Counter-Strike: Global Offensive remained popular for so long?"
run T9 kw   "CS:GO esports popularity player count"
run T9 ent  "Counter-Strike Global Offensive"

# T10 conceptual method + comparison (carbon dating, topic 10)
run T10 nlq "What are the limitations of radiocarbon dating?"
run T10 kw  "radiocarbon dating limitations accuracy calibration"
run T10 ent "carbon-14 dating vs potassium-argon dating"
