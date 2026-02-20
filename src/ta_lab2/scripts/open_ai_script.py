# -*- coding: utf-8 -*-
"""
Created on Sat Nov 22 20:46:38 2025

@author: asafi
"""
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
import os
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[3]  # c:\users\asafi\downloads\ta_lab2

# if your file is called openai_config.env in the project root:
load_dotenv(ROOT / "openai_config.env")

api_key = os.environ.get("OPENAI_API_KEY")
print("OPENAI_API_KEY loaded?", bool(api_key))

client = OpenAI(api_key=api_key)


def load_stats_csv(path: str) -> str:
    df = pd.read_csv(path)
    # Keep it small-ish: maybe only interesting columns
    cols = [
        "stat_id",
        "table_name",
        "test_name",
        "asset_id",
        "tf",
        "period",
        "status",
        "actual",
        "expected",
        "extra",
        "checked_at",
    ]
    df = df[cols]
    return df.to_csv(index=False)


def ask_chatgpt_about_stats(csv_text: str, run_label: str) -> str:
    prompt = f"""
You are my data QA assistant for a crypto EMA pipeline (ta_lab2).

Below is a CSV dump of test results for this run: {run_label}.

Columns:
stat_id, table_name, test_name, asset_id, tf, period, status, actual, expected, extra, checked_at

Tasks:
1. Summarize overall health (how many PASS/WARN/FAIL, and any patterns).
2. For each WARN or FAIL, explain in plain language what it means.
3. Suggest the next 2–3 concrete actions (SQL queries or checks) I should run.
4. Keep it concise and actionable.

CSV:
{csv_text}
"""

    resp = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": "You are a highly technical data QA assistant helping with EMA and multi-timeframe stats.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    return resp.choices[0].message.content


if __name__ == "__main__":
    csv_path = r"C:\Users\asafi\Downloads\cmc_price_histories\stats\ema_multi_tf_stats_check_2025_11_22.csv"
    csv_text = load_stats_csv(csv_path)
    summary = ask_chatgpt_about_stats(csv_text, run_label="2025-11-22 evening run")
    print(summary)
