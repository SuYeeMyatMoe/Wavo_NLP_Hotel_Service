export default function ({parentElement, data, setStateValue}) {
  const label = parentElement.querySelector("small");
  const state = parentElement.wavoRealtime || (parentElement.wavoRealtime = {});
  if (!data.url || !data.token) { label.textContent = "Updates refresh automatically"; return; }
  const fingerprint = data.user + ":" + data.token;
  if (state.fingerprint === fingerprint) return;
  state.client?.removeAllChannels();
  state.fingerprint = fingerprint;
  // The pinned SDK is concatenated into this ES module, not attached to window.
  state.client = supabase.createClient(data.url, data.key, {
    auth: {persistSession: false, autoRefreshToken: false, detectSessionInUrl: false}
  });
  state.client.realtime.setAuth(data.token);
  state.channel = state.client.channel("wavo:user:" + data.user, {config: {private: true}})
    .on("broadcast", {event: "notification"}, ({payload}) => {
      if (payload?.id) setStateValue("revision", payload.id);
    }).subscribe(status => {
      label.textContent = status === "SUBSCRIBED" ? "Live updates connected" : "Reconnecting · inbox polling remains active";
    });
  return () => { state.client?.removeAllChannels(); state.fingerprint = null; };
}
