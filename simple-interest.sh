#!/bin/bash
# ---------------------------------------------------------
# Career-Pilot | Simple Interest Calculator
# ---------------------------------------------------------
# Author  : Ashish Sharma
# Purpose : Utility script to demonstrate simple interest calculation
# Formula : SI = (P × R × T) / 100
# ---------------------------------------------------------

echo "================ Career-Pilot Utility ================"
echo "          Simple Interest Calculator (Shell)          "
echo "======================================================"

# Input values
read -p "Enter Principal Amount (₹): " principal
read -p "Enter Annual Interest Rate (%): " rate
read -p "Enter Time (in years): " time

# Validate input
if [[ -z "$principal" || -z "$rate" || -z "$time" ]]; then
  echo "⚠️  Error: All fields are required. Please try again."
  exit 1
fi

# Calculate Simple Interest
interest=$(echo "scale=2; ($principal * $rate * $time) / 100" | bc)

# Display result
echo "------------------------------------------------------"
echo "Principal Amount : ₹$principal"
echo "Rate of Interest : $rate%"
echo "Time Duration    : $time year(s)"
echo "------------------------------------------------------"
echo "➡️  Simple Interest = ₹$interest"
echo "------------------------------------------------------"

echo "✅ Calculation completed successfully!"
