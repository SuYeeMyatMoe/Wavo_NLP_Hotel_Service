"""Decision-first service insights, with actions backed by authorized records."""

import altair as alt
import pandas as pd
import streamlit as st
from hotel.ui_copy import words
from hotel.ui_client import request

BRONZE = "#DDB479"
GREEN = "#8AB499"


def render(jump):
    st.title("Service analytics")
    view = st.segmented_control(
        "Analytics view",
        ["Live overview", "Trends"],
        default="Live overview",
        key="analytics_view",
    )
    days = 30
    if view == "Trends":
        days = st.selectbox(
            "Date range",
            [7, 30, 90, 0],
            index=1,
            format_func=lambda period: f"Last {period} days" if period else "All time",
            key="insights_period",
        )
    data = request("GET", "/insights", params={"days": days})
    scope = "All hotel teams" if data["scope"] == "Hotel-wide" else data["scope"]
    st.caption(f"{scope} · Updated {data['as_of'][:16].replace('T', ' ')} UTC")
    if view == "Trends":
        trends(data)
        return
    current_work(data, jump)


def current_work(data, jump):
    st.subheader("Current workload")
    st.caption("Includes all open requests, regardless of when they were created.")
    c = data["current"]
    known_targets = data["unresolved"] - c["awaiting_guest"] - c["missing_deadlines"]
    with st.container(horizontal=True, key="analytics_summary"):
        st.metric(
            "Open requests",
            data["unresolved"],
            border=True,
            help="All unresolved requests you are authorized to see, regardless of the selected performance period.",
        )
        st.metric(
            "Need attention",
            c["attention"],
            border=True,
            help="Distinct requests needing human review, assignment, overdue work or guest confirmation; reasons can overlap.",
        )
        st.metric(
            "Past service target",
            c["overdue_service"] if known_targets else "—",
            border=True,
            help=f"{known_targets} open requests have a recorded service deadline; {c['missing_deadlines']} have none. Requests awaiting confirmation are excluded.",
        )
        st.metric(
            "Awaiting guest",
            c["awaiting_guest"],
            border=True,
            help="Work reported complete by staff stays open until the guest confirms.",
        )

    immediate = sum(
        r["Priority"] in {"Critical", "Unassessed"} for r in data["attention"]
    )
    if immediate:
        st.error(
            f"{immediate} request(s) need immediate safety or urgency review. Start with the row with the highest priority below.",
            title="Reception review comes first",
        )
        if c["unassigned"]:
            st.caption(
                f"{c['unassigned']} open request(s) also have no assigned worker. Review the dispatch blockers in each request."
            )
    elif c["unassigned"]:
        st.warning(
            f"{c['unassigned']} open request(s) have no assigned worker.",
            title="Review the dispatch blockers",
        )
        st.caption(
            "Check approved guidance, guest agreement and roster availability in the request before retrying assignment."
        )
    elif c["overdue_service"]:
        st.warning(
            f"{c['overdue_service']} request(s) passed their recorded service target.",
            title="Follow up on delayed work",
        )
    elif c["awaiting_guest"]:
        st.info(
            f"Follow up on {c['awaiting_guest']} reported completion(s). Guest silence is not confirmation."
        )
    elif not data["unresolved"]:
        st.success("No open service requests in your scope.")
    if c["missing_deadlines"]:
        st.caption(
            f"Deadline coverage: {c['missing_deadlines']} open request(s) have no recorded service target. They are not counted as on time."
        )

    st.subheader("Needs attention now")
    alerts = data["attention"][:12]
    if alerts:
        ids = tuple(r["id"] for r in alerts)

        def select_request():
            click = st.session_state.get("insights_open")
            if click and 0 <= click["row"] < len(ids):
                st.session_state.insights_open_ref = ids[click["row"]]

        if ref := st.session_state.pop("insights_open_ref", None):
            jump("My work", ref)
            return
        st.dataframe(
            [
                {
                    "Room": r["Room"],
                    "Problem": words(r["Problem"]),
                    "Priority": r["Priority"],
                    "Needs attention": r["Needs attention"],
                    "Open (min)": r["Open (min)"],
                    "Action": "Open request",
                }
                for r in alerts
            ],
            hide_index=True,
            row_height=48,
            column_order=[
                "Room", "Action", "Problem", "Priority", "Needs attention", "Open (min)"
            ],
            height=min(360, 55 + 48 * len(alerts)),
            column_config={
                "Action": st.column_config.ButtonColumn(
                    on_click=select_request, key="insights_open", width=135
                )
            },
            alt="Requests needing attention, ordered by urgency and age, with buttons to open the work record",
        )
        st.caption(
            f"Showing {len(alerts)} of {c['attention']} requests, highest urgency first. Open a request for its constraints and next action."
        )
    else:
        st.caption("No exceptions recorded. Continue the assigned work in My work.")

    st.subheader("Team workload")
    if data["workload"]:
        st.dataframe(
            data["workload"],
            hide_index=True,
            alt="Open requests, progress, guest confirmations and delays by team member",
        )
        st.caption(
            "Current assigned workload; this is not a staff productivity score. Unassigned work remains visible."
        )
    else:
        st.caption("No open assignments.")



def trends(data):
    st.subheader("Service outcomes")
    total = data["tickets"]
    minutes = data["median_resolution_minutes"]
    with st.container(horizontal=True, key="analytics_outcomes"):
        st.metric(
            "Confirmed resolution",
            f"{100 * data['confirmation_rate']:.0f}%" if total else "—",
            border=True,
            help=f"{data['confirmed']} currently closed requests with explicit confirmation out of {total} requests opened in this period.",
        )
        st.metric(
            "Typical resolution",
            f"{minutes:.0f} min" if minutes is not None else "—",
            border=True,
            help=f"Median time from opening the request to final confirmation. Sample: {data['resolution_sample']} confirmed requests opened in the selected period.",
        )
        st.metric(
            "Needed another attempt",
            data["reopened"],
            border=True,
            help=f"Distinct requests opened in this period that a guest rejected or reopened at least once; denominator {total}.",
        )
        st.metric(
            "Calls resolved without a task",
            data["calls"]["self_service"],
            border=True,
            help=f"Of {data['calls']['ended']} ended inbound calls opened in this period, these recorded resolution confirmed by the guest, no service task and no staff join. Not an estimate of money or time saved.",
        )
    st.caption(
        f"{total} requests opened in the selected period · {data['resolution_sample']} confirmed resolution times · {data['calls']['ended']} ended inbound calls. Small samples are descriptive, not performance guarantees."
    )

    left, right = st.columns(2)
    with left, st.container(border=True):
        st.subheader("Demand & confirmed outcomes")
        daily = pd.DataFrame(data["daily"])
        if total or (not daily.empty and daily["Confirmed"].sum()):
            melted = daily.melt("Date", var_name="Measure", value_name="Requests")
            chart = (
                alt.Chart(melted)
                .mark_line(point=True)
                .encode(
                    x=alt.X(
                        "Date:T",
                        title=None,
                        axis=alt.Axis(format="%d %b", labelAngle=0),
                    ),
                    y=alt.Y(
                        "Requests:Q", title="Requests", axis=alt.Axis(tickMinStep=1)
                    ),
                    color=alt.Color(
                        "Measure:N",
                        scale=alt.Scale(
                            domain=["Opened", "Confirmed"], range=[BRONZE, GREEN]
                        ),
                        legend=alt.Legend(orient="bottom"),
                    ),
                    tooltip=["Date:T", "Measure:N", "Requests:Q"],
                )
                .properties(height=220)
            )
            active_days = daily[(daily["Opened"] + daily["Confirmed"]) > 0]
            if len(active_days) == 1:
                # A single demo day is a count comparison, not a trend. Avoid
                # implying a measured month of zero demand before data existed.
                chart = (
                    alt.Chart(
                        melted.groupby("Measure", as_index=False)["Requests"].sum()
                    )
                    .mark_bar()
                    .encode(
                        y=alt.Y("Measure:N", title=None),
                        x=alt.X("Requests:Q", axis=alt.Axis(tickMinStep=1)),
                        color=alt.Color(
                            "Measure:N",
                            scale=alt.Scale(
                                domain=["Opened", "Confirmed"], range=[BRONZE, GREEN]
                            ),
                            legend=None,
                        ),
                        tooltip=["Measure:N", "Requests:Q"],
                    )
                    .properties(height=220)
                )
                st.caption(
                    "Only one day of activity is recorded. These are counts, not an established trend."
                )
            st.altair_chart(
                chart, alt="Requests opened and explicitly confirmed by date"
            )
            st.caption(
                "Confirmations are counted on their event date and may relate to requests opened earlier. Dates use UTC."
            )
        else:
            st.caption("No request or confirmation activity in this period.")
    with right, st.container(border=True):
        st.subheader("What is keeping work open?")
        if data["open_problems"]:
            frame = pd.DataFrame(data["open_problems"][:6])
            frame["Problem"] = frame["Problem"].map(words)
            chart = (
                alt.Chart(frame)
                .mark_bar(color=BRONZE, cornerRadiusEnd=3)
                .encode(
                    y=alt.Y(
                        "Problem:N",
                        sort="-x",
                        title=None,
                        axis=alt.Axis(labelLimit=220),
                    ),
                    x=alt.X(
                        "Requests:Q",
                        title="Open requests",
                        axis=alt.Axis(tickMinStep=1),
                    ),
                    tooltip=["Problem:N", "Requests:Q"],
                )
                .properties(height=220)
            )
            st.altair_chart(
                chart, alt="Most frequent problems among currently open requests"
            )
            st.caption(
                "Use repeat problems to review equipment or approved procedures. Missing details need clarification."
            )
        else:
            st.caption("No unresolved problems.")

    if data["repeat_rooms"]:
        with st.expander("Rooms with repeated requests"):
            st.dataframe(
                data["repeat_rooms"],
                hide_index=True,
                alt="Rooms with more than one request opened in the selected period",
            )
            st.caption(
                "Multiple requests do not necessarily mean a failed repair or the same guest. Review the records before acting."
            )
    with st.expander("Data quality & sentiment"):
        st.write(
            f"{data['missing_problem']} of {total} requests lack a specific problem label. {data['missing_completion']} closed records have no explicit confirmation event and are excluded from confirmed outcomes."
        )
        if data["sentiments"]:
            st.dataframe(
                [
                    {"Sentiment": label, "Requests": count}
                    for label, count in data["sentiments"].items()
                ],
                hide_index=True,
                alt="Sentiment counts for requests opened in the selected period",
            )
        st.caption(
            "Sentiment is an heuristic for English text, not guest satisfaction, urgency or revenue. Missing scores stay labelled. Demo and test records are included; these are not production business results."
        )
