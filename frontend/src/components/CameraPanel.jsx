import { useEffect, useState } from "react";
import {
  Camera,
  CircleStop,
  LoaderCircle,
  Play,
  Save,
} from "lucide-react";

import {
  getBackblazeCredentialsStatus,
  getCameraSettings,
  getRecordingStatus,
  saveBackblazeCredentials,
  saveCameraSettings,
  startRecording,
  stopRecording,
} from "../services/cameraApi";


export default function CameraPanel() {
  const [settings, setSettings] = useState(null);
  const [status, setStatus] = useState(null);
  const [pending, setPending] = useState(null);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);
  const [credentialsStatus, setCredentialsStatus] = useState(null);
  const [backblazeKeyId, setBackblazeKeyId] = useState("");
  const [
    backblazeApplicationKey,
    setBackblazeApplicationKey,
  ] = useState("");

  async function loadSettings() {
    try {
      setSettings(await getCameraSettings());
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function loadCredentialsStatus() {
    try {
      setCredentialsStatus(
        await getBackblazeCredentialsStatus(),
      );
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function refreshStatus() {
    try {
      setStatus(await getRecordingStatus());
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function saveSettings() {
    setPending("save");
    setMessage(null);
    setError(null);

    try {
      const saved = await saveCameraSettings(
        settings,
      );

      setSettings(saved);

      setMessage(
        anyRecording
          ? "Settings saved. Recording changes apply on the next recorder restart."
          : "Camera settings saved.",
      );
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setPending(null);
    }
  }

  async function saveCredentials() {
    setPending("credentials");
    setMessage(null);
    setError(null);

    try {
      const result =
        await saveBackblazeCredentials(
          backblazeKeyId,
          backblazeApplicationKey,
        );

      setCredentialsStatus(result);

      // Never retain credentials in browser state
      // after they have been saved.
      setBackblazeKeyId("");
      setBackblazeApplicationKey("");

      setMessage(
        "Backblaze credentials saved.",
      );
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setPending(null);
    }
  }

  async function runCommand(command) {
    setPending(command);
    setMessage(null);
    setError(null);

    try {
      const result =
        command === "start"
          ? await startRecording()
          : await stopRecording();

      setStatus(result);

      setMessage(
        command === "start"
          ? "Recording start requested."
          : "Recording stopped.",
      );
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setPending(null);
    }
  }

  function updateSetting(key, value) {
    setSettings((current) => ({
      ...current,
      [key]: value,
    }));
  }

  function updateCamera(index, key, value) {
    setSettings((current) => ({
      ...current,
      cameras: current.cameras.map(
        (camera, cameraIndex) =>
          cameraIndex === index
            ? {
                ...camera,
                [key]: value,
              }
            : camera,
      ),
    }));
  }

  useEffect(() => {
    loadSettings();
    loadCredentialsStatus();
    refreshStatus();

    const interval = window.setInterval(
      refreshStatus,
      3000,
    );

    return () => {
      window.clearInterval(interval);
    };
  }, []);

  if (!settings) {
    return null;
  }

  const anyRecording =
    status?.cameras?.some(
      (camera) => camera.running,
    ) ?? false;

  return (
    <section className="mt-8 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-start gap-4">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-blue-600 text-white">
          <Camera size={24} />
        </div>

        <div className="flex-1">
          <h2 className="text-xl font-semibold text-slate-950">
            CCTV Cameras
          </h2>

          <p className="mt-1 text-sm text-slate-600">
            ESP32-CAM recording and configuration.
          </p>
        </div>

        <div
          className={`rounded-full px-4 py-2 text-sm font-semibold ${
            anyRecording
              ? "bg-red-100 text-red-700"
              : "bg-slate-100 text-slate-600"
          }`}
        >
          {anyRecording ? "Recording" : "Stopped"}
        </div>
      </div>

      <div className="mt-6 rounded-2xl bg-slate-50 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-slate-900">
              GStreamer
            </div>

            <div className="mt-1 text-sm text-slate-500">
              {status?.gstreamer_available
                ? "Available"
                : "Unavailable"}
            </div>
          </div>

          <span
            className={`rounded-full px-3 py-1 text-xs font-semibold ${
              status?.gstreamer_available
                ? "bg-emerald-100 text-emerald-700"
                : "bg-red-100 text-red-700"
            }`}
          >
            {status?.gstreamer_available
              ? "Ready"
              : "Not Ready"}
          </span>
        </div>

        {status?.gstreamer_error && (
          <p className="mt-3 text-xs text-red-700">
            {status.gstreamer_error}
          </p>
        )}
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <label className="rounded-2xl bg-slate-50 p-4">
          <span className="text-sm font-medium text-slate-700">
            Record automatically when backend starts
          </span>

          <div className="mt-3 flex items-center gap-3">
            <input
              type="checkbox"
              checked={settings.recording_enabled}
              onChange={(event) =>
                updateSetting(
                  "recording_enabled",
                  event.target.checked,
                )
              }
              className="h-5 w-5"
            />

            <span className="text-sm">
              {settings.recording_enabled
                ? "Enabled"
                : "Disabled"}
            </span>
          </div>
        </label>

        <NumberSetting
          label="Segment duration"
          value={settings.segment_seconds}
          suffix="seconds"
          min={10}
          onChange={(value) =>
            updateSetting(
              "segment_seconds",
              value,
            )
          }
        />

        <NumberSetting
          label="Frame rate"
          value={settings.frame_rate}
          suffix="fps"
          min={1}
          onChange={(value) =>
            updateSetting(
              "frame_rate",
              value,
            )
          }
        />

        <NumberSetting
          label="Video bitrate"
          value={settings.video_bitrate_kbps}
          suffix="kbps"
          min={100}
          onChange={(value) =>
            updateSetting(
              "video_bitrate_kbps",
              value,
            )
          }
        />
        <NumberSetting
          label="Recorder restart delay"
          value={
            settings.recorder_restart_delay_seconds
          }
          suffix="seconds"
          min={1}
          onChange={(value) =>
            updateSetting(
              "recorder_restart_delay_seconds",
              value,
            )
          }
        />

        <label className="rounded-2xl bg-slate-50 p-4 md:col-span-2">
          <span className="text-sm font-medium text-slate-700">
            Temporary recording directory
          </span>

          <input
            type="text"
            value={settings.recording_directory}
            onChange={(event) =>
              updateSetting(
                "recording_directory",
                event.target.value,
              )
            }
            className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 font-mono text-sm"
          />
        </label>
      </div>
      <div className="mt-6 rounded-2xl border border-slate-200 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold text-slate-950">
              Backblaze B2
            </h3>

            <p className="mt-1 text-sm text-slate-500">
              Upload completed CCTV segments to
              Backblaze B2.
            </p>
          </div>

          <span
            className={`rounded-full px-3 py-1 text-xs font-semibold ${
              credentialsStatus?.configured
                ? "bg-emerald-100 text-emerald-700"
                : "bg-amber-100 text-amber-700"
            }`}
          >
            {credentialsStatus?.configured
              ? "Credentials configured"
              : "Credentials not configured"}
          </span>
        </div>

        {credentialsStatus?.configured && (
          <p className="mt-3 text-xs text-slate-500">
            Key ID ending in{" "}
            <span className="font-mono font-semibold">
              {credentialsStatus.key_id_suffix}
            </span>
          </p>
        )}

        <div className="mt-5 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <label className="rounded-2xl bg-slate-50 p-4">
            <span className="text-sm font-medium text-slate-700">
              Upload enabled
            </span>

            <div className="mt-3 flex items-center gap-3">
              <input
                type="checkbox"
                checked={settings.b2_upload_enabled}
                onChange={(event) =>
                  updateSetting(
                    "b2_upload_enabled",
                    event.target.checked,
                  )
                }
                className="h-5 w-5"
              />

              <span className="text-sm">
                {settings.b2_upload_enabled
                  ? "Enabled"
                  : "Disabled"}
              </span>
            </div>
          </label>

          <TextField
            label="Region"
            value={settings.b2_region}
            mono
            onChange={(value) =>
              updateSetting(
                "b2_region",
                value,
              )
            }
          />

          <TextField
            label="Bucket"
            value={settings.b2_bucket}
            mono
            onChange={(value) =>
              updateSetting(
                "b2_bucket",
                value,
              )
            }
          />

          <NumberSetting
            label="Upload rate"
            value={settings.b2_upload_rate_kbps}
            suffix="KiB/s"
            min={1}
            onChange={(value) =>
              updateSetting(
                "b2_upload_rate_kbps",
                value,
              )
            }
          />
        </div>

        <div className="mt-5 border-t border-slate-200 pt-5">
          <div className="text-sm font-semibold text-slate-900">
            Credentials
          </div>

          <p className="mt-1 text-xs text-slate-500">
            Credentials are stored only on this
            Raspberry Pi and are not committed to Git.
          </p>

          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <label className="block">
              <span className="text-sm font-medium text-slate-700">
                Application Key ID
              </span>

              <input
                type="password"
                value={backblazeKeyId}
                autoComplete="off"
                onChange={(event) =>
                  setBackblazeKeyId(
                    event.target.value,
                  )
                }
                placeholder={
                  credentialsStatus?.configured
                    ? "Enter only to replace"
                    : "Enter Key ID"
                }
                className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-sm"
              />
            </label>

            <label className="block">
              <span className="text-sm font-medium text-slate-700">
                Application Key
              </span>

              <input
                type="password"
                value={backblazeApplicationKey}
                autoComplete="new-password"
                onChange={(event) =>
                  setBackblazeApplicationKey(
                    event.target.value,
                  )
                }
                placeholder={
                  credentialsStatus?.configured
                    ? "Enter only to replace"
                    : "Enter Application Key"
                }
                className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-sm"
              />
            </label>
          </div>

          <button
            type="button"
            onClick={saveCredentials}
            disabled={
              pending !== null ||
              !backblazeKeyId.trim() ||
              !backblazeApplicationKey.trim()
            }
            className="mt-4 flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-3 text-sm font-semibold text-white disabled:opacity-50"
          >
            <Save size={17} />
            Save Credentials
          </button>
        </div>
      </div>

      <div className="mt-6 grid gap-5 lg:grid-cols-2">
        {settings.cameras.map(
          (camera, index) => {
            const cameraStatus =
              status?.cameras?.find(
                (item) =>
                  item.key === camera.key,
              );

            return (
              <div
                key={camera.key}
                className="rounded-2xl border border-slate-200 p-5"
              >
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h3 className="font-semibold text-slate-950">
                      {camera.name}
                    </h3>

                    <p className="mt-1 font-mono text-xs text-slate-500">
                      {camera.key}
                    </p>
                  </div>

                  <span
                    className={`rounded-full px-3 py-1 text-xs font-semibold ${
                      cameraStatus?.running
                        ? "bg-red-100 text-red-700"
                        : camera.enabled
                          ? "bg-slate-100 text-slate-600"
                          : "bg-amber-100 text-amber-700"
                    }`}
                  >
                    {cameraStatus?.running
                      ? "Recording"
                      : camera.enabled
                        ? "Idle"
                        : "Disabled"}
                  </span>
                </div>

                <div className="mt-5 space-y-4">
                  <label className="flex items-center gap-3">
                    <input
                      type="checkbox"
                      checked={camera.enabled}
                      onChange={(event) =>
                        updateCamera(
                          index,
                          "enabled",
                          event.target.checked,
                        )
                      }
                      className="h-5 w-5"
                    />

                    <span className="text-sm font-medium text-slate-700">
                      Camera enabled
                    </span>
                  </label>

                  <TextField
                    label="Name"
                    value={camera.name}
                    onChange={(value) =>
                      updateCamera(
                        index,
                        "name",
                        value,
                      )
                    }
                  />

                  <TextField
                    label="IP address / host"
                    value={camera.host}
                    mono
                    onChange={(value) =>
                      updateCamera(
                        index,
                        "host",
                        value,
                      )
                    }
                  />

                  <TextField
                    label="Stream path"
                    value={camera.stream_path}
                    mono
                    onChange={(value) =>
                      updateCamera(
                        index,
                        "stream_path",
                        value,
                      )
                    }
                  />

                  <NumberField
                    label="Control port"
                    value={camera.control_port}
                    min={1}
                    max={65535}
                    onChange={(value) =>
                      updateCamera(
                        index,
                        "control_port",
                        value,
                      )
                    }
                  />
                </div>

                {cameraStatus?.last_error && (
                  <div className="mt-4 rounded-xl bg-red-50 p-3 text-xs text-red-700">
                    {cameraStatus.last_error}
                  </div>
                )}

                {cameraStatus?.restart_count > 0 && (
                  <div className="mt-4 rounded-xl bg-amber-50 p-3 text-xs text-amber-700">
                    Automatic recorder recoveries:{" "}
                    {cameraStatus.restart_count}
                  </div>
                )}

                {cameraStatus?.current_fragment && (
                  <Fragment
                    label="Current segment"
                    value={
                      cameraStatus.current_fragment
                    }
                  />
                )}

                {cameraStatus?.last_completed_fragment && (
                  <Fragment
                    label="Last completed segment"
                    value={
                      cameraStatus.last_completed_fragment
                    }
                  />
                )}
              </div>
            );
          },
        )}
      </div>

      <div className="mt-6 flex flex-wrap gap-3">
        <button
          type="button"
          onClick={saveSettings}
          disabled={pending !== null}
          className="flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-3 text-sm font-semibold text-white disabled:opacity-50"
        >
          <Save size={17} />
          Save Settings
        </button>

        <button
          type="button"
          onClick={() =>
            runCommand("start")
          }
          disabled={
            pending !== null ||
            anyRecording ||
            !status?.gstreamer_available
          }
          className="flex items-center gap-2 rounded-xl bg-red-600 px-4 py-3 text-sm font-semibold text-white disabled:opacity-50"
        >
          {pending === "start" ? (
            <LoaderCircle
              size={17}
              className="animate-spin"
            />
          ) : (
            <Play size={17} />
          )}

          Start Recording
        </button>

        <button
          type="button"
          onClick={() =>
            runCommand("stop")
          }
          disabled={
            pending !== null ||
            !anyRecording
          }
          className="flex items-center gap-2 rounded-xl bg-slate-200 px-4 py-3 text-sm font-semibold text-slate-800 disabled:opacity-50"
        >
          <CircleStop size={17} />
          Stop Recording
        </button>
      </div>

      {message && (
        <p className="mt-4 text-sm text-emerald-700">
          {message}
        </p>
      )}

      {error && (
        <p className="mt-4 text-sm text-red-700">
          {error}
        </p>
      )}
    </section>
  );
}


function NumberSetting({
  label,
  value,
  suffix,
  min,
  onChange,
}) {
  return (
    <label className="rounded-2xl bg-slate-50 p-4">
      <span className="text-sm font-medium text-slate-700">
        {label}
      </span>

      <div className="mt-2 flex items-center gap-2">
        <input
          type="number"
          min={min}
          value={value}
          onChange={(event) =>
            onChange(Number(event.target.value))
          }
          className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2"
        />

        <span className="text-xs text-slate-500">
          {suffix}
        </span>
      </div>
    </label>
  );
}


function TextField({
  label,
  value,
  onChange,
  mono = false,
}) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-slate-700">
        {label}
      </span>

      <input
        type="text"
        value={value}
        onChange={(event) =>
          onChange(event.target.value)
        }
        className={`mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm ${
          mono ? "font-mono" : ""
        }`}
      />
    </label>
  );
}


function NumberField({
  label,
  value,
  min,
  max,
  onChange,
}) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-slate-700">
        {label}
      </span>

      <input
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(event) =>
          onChange(Number(event.target.value))
        }
        className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm"
      />
    </label>
  );
}


function Fragment({ label, value }) {
  return (
    <div className="mt-4 rounded-xl bg-slate-50 p-3">
      <div className="text-xs font-semibold text-slate-600">
        {label}
      </div>

      <div className="mt-1 break-all font-mono text-xs text-slate-500">
        {value}
      </div>
    </div>
  );
}