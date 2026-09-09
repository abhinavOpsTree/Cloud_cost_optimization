import json
import os

import pandas as pd
import requests
import streamlit as st

from app.core.config import settings


API = os.getenv(
    "API_URL",
    "http://127.0.0.1:8000/api",
).rstrip("/")


st.set_page_config(
    page_title="SpendSmart EC2 Cost Optimization",
    page_icon="💸",
    layout="wide",
)

st.title("SpendSmart Cost Optimization")
st.caption(
    "Full UnitEconPro Swagger catalog • Processing scope: EC2 only"
)


def api_get(path, default=None, timeout=30):
    try:
        response = requests.get(
            API + path,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except Exception:
        return default


def api_post(path, timeout=120):
    response = requests.post(
        API + path,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


with st.sidebar:
    st.header("Source")

    st.code(
        settings.spendsmart_base_url
    )

    if st.button(
        "Test SpendSmart Health",
        use_container_width=True,
    ):
        result = api_get(
            "/spendsmart/health",
            None,
        )

        if result is None:
            st.error("Source health check failed.")
        else:
            st.success("SpendSmart reachable")
            st.json(result)

    if st.button(
        "Ingest EC2",
        type="primary",
        use_container_width=True,
    ):
        try:
            with st.spinner(
                "Fetching EC2 data from SpendSmart..."
            ):
                result = api_post(
                    "/ingestion/ec2"
                )

            st.success("EC2 ingestion complete")
            st.json(result)

        except Exception as exc:
            st.error(str(exc))

    if st.button(
        "Run EC2 Analysis",
        use_container_width=True,
    ):
        try:
            result = api_post(
                "/ec2/analysis/run"
            )

            st.success("EC2 analysis complete")
            st.json(result)

        except Exception as exc:
            st.error(str(exc))


tabs = st.tabs([
    "EC2 Overview",
    "Inventory",
    "Lifecycle / AMIs",
    "Optimizations",
    "Swagger Catalog",
    "AI",
])


with tabs[0]:
    summary = api_get(
        "/ec2/summary",
        {
            "instances": 0,
            "running": 0,
            "stopped": 0,
            "monthly_cost": 0,
            "potential_monthly_savings": 0,
            "lifecycle_records": 0,
            "ami_count": 0,
        },
    )

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Instances",
        summary["instances"],
    )

    c2.metric(
        "Running",
        summary["running"],
    )

    c3.metric(
        "Stopped",
        summary["stopped"],
    )

    c4.metric(
        "Potential Savings",
        f"${summary['potential_monthly_savings']:,.2f}",
    )

    st.subheader("SpendSmart EC2 Summary")

    source_summary = api_get(
        "/spendsmart/ec2/summary",
        {},
    )

    st.json(source_summary)

    st.subheader("Top EC2 Cost")

    top = api_get(
        "/ec2/top-cost?limit=20",
        [],
    )

    if top:
        st.dataframe(
            pd.DataFrame(top),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No normalized EC2 records yet.")


with tabs[1]:
    inventory = api_get(
        "/ec2/inventory?limit=500",
        [],
    )

    if inventory:
        df = pd.DataFrame(inventory)

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )

        selected = st.selectbox(
            "Inspect instance metadata",
            [""] + df["instance_id"].astype(str).tolist(),
        )

        if selected:
            metadata = api_get(
                f"/spendsmart/ec2/instances/{selected}/metadata",
                {},
            )

            st.json(metadata)

    else:
        st.info("No EC2 inventory loaded.")


with tabs[2]:
    left, right = st.columns(2)

    with left:
        st.subheader("Lifecycle")

        rows = api_get(
            "/ec2/lifecycle?limit=500",
            [],
        )

        if rows:
            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No lifecycle data loaded.")

    with right:
        st.subheader("AMI Inventory")

        rows = api_get(
            "/ec2/amis?limit=500",
            [],
        )

        if rows:
            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No AMI data loaded.")


with tabs[3]:
    st.subheader("SpendSmart EC2 Optimizations")

    st.json(
        api_get(
            "/spendsmart/ec2/optimizations",
            {},
        )
    )

    st.subheader("SpendSmart Recommendations")

    st.json(
        api_get(
            "/spendsmart/recommendations",
            {},
        )
    )

    st.subheader("Local EC2 Findings")

    findings = api_get(
        "/ec2/findings",
        [],
    )

    if findings:
        st.dataframe(
            pd.DataFrame(findings),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No local EC2 findings yet.")


with tabs[4]:
    st.subheader("Full UnitEconPro Endpoint Catalog")

    catalog = api_get(
        "/source-catalog/endpoints",
        {},
    )

    st.json(catalog)

    st.subheader("Swagger Schema Names")

    schemas = api_get(
        "/source-catalog/schemas",
        {},
    )

    st.json(schemas)

    st.info(
        "Only EC2 is currently processed downstream. "
        "Other Swagger services are cataloged for later activation."
    )


with tabs[5]:
    latest = api_get(
        "/ai/ec2-summary/latest",
        {
            "content":
                "No EC2 AI summary generated yet."
        },
    )

    st.subheader("Latest EC2 AI Summary")
    st.write(
        latest.get(
            "content",
            "",
        )
    )

    if st.button(
        "Generate EC2 AI Summary"
    ):
        try:
            result = api_post(
                "/ai/ec2-summary"
            )

            st.success("Summary generated")
            st.write(
                result.get(
                    "content",
                    "",
                )
            )

        except Exception as exc:
            st.error(str(exc))

    st.divider()

    st.subheader("EC2 FinOps Chat")

    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": (
                    "Ask about SpendSmart EC2 cost, "
                    "inventory, utilization, lifecycle, "
                    "or optimization."
                ),
            }
        ]

    for message in st.session_state.messages:
        with st.chat_message(
            message["role"]
        ):
            st.markdown(
                message["content"]
            )

    prompt = st.chat_input(
        "Ask about EC2..."
    )

    if prompt:
        st.session_state.messages.append(
            {
                "role": "user",
                "content": prompt,
            }
        )

        with st.chat_message("user"):
            st.markdown(prompt)

        try:
            if not settings.groq_api_key:
                raise ValueError(
                    "GROQ_API_KEY is not configured"
                )

            from groq import Groq

            context = {
                "summary": api_get(
                    "/ec2/summary",
                    {},
                ),
                "top_cost": api_get(
                    "/ec2/top-cost?limit=15",
                    [],
                ),
                "findings": api_get(
                    "/ec2/findings",
                    [],
                ),
            }

            client = Groq(
                api_key=settings.groq_api_key.strip()
            )

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are the SpendSmart EC2 FinOps assistant. "
                        "Use only supplied account-specific evidence. "
                        "Do not invent costs, savings, resources, or utilization.\n\n"
                        "EC2 CONTEXT:\n"
                        + json.dumps(
                            context,
                            default=str,
                        )
                    ),
                }
            ]

            messages.extend(
                st.session_state.messages[-10:]
            )

            response = (
                client.chat.completions.create(
                    model=settings.llm_model,
                    messages=messages,
                    temperature=0.2,
                )
            )

            answer = (
                response.choices[0]
                .message.content
                or ""
            )

            with st.chat_message(
                "assistant"
            ):
                st.markdown(answer)

            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": answer,
                }
            )

        except Exception as exc:
            st.error(str(exc))


st.divider()
st.caption(
    "SpendSmart / UnitEconPro — EC2 processing focus"
)
