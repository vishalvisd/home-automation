import { useEffect, useState } from "react";
import {
  Camera,
  CircleStop,
  LoaderCircle,
  Play,
  Plus,
  Save,
  Trash2,
} from "lucide-react";

import {
  getBackblazeCredentialsStatus,
  getCameraSettings,
  getPresetStatus,
  getRecordingStatus,
  saveBackblazeCredentials,
  saveCameraSettings,
  startRecording,
  stopRecording,
} from "../services/cameraApi";


const SOURCE_TYPES = [
  {
    value: "esp32_mjpeg",
    label: "ESP32-CAM (MJPEG over HTTP)",
  },
  {
    value: "rtsp",
    label: "RTSP camera (commercial IP camera)",
  },
];


function nextCameraKey(cameras) {
  let number = 1;

  while (cameras.some((camera) => camera.key === `cam${number}`)) {
    number += 1;
  }

  return `cam${number}`;
}


export default function CameraPanel() {
  const [settings, setSettings] = useState(null);
  const [status, setStatus] = useState(null);
  const [presetStatus, setPresetStatus] =
    useState(null);
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

  async function refreshPresetStatus() {
    try {
      setPresetStatus(
        await getPresetStatus(),
      );
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
      await refreshPresetStatus();

      setMessage(
        anyRecording
          ? "Settings saved. Recording changes apply on the next recorder restart. Day/night times apply on the next preset check."
          : "Camera settings saved. Day/night times apply on the next preset check.",
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

  function addCamera() {
    setSettings((current) => {
      const key = nextCameraKey(current.cameras);
      const number = key.replace("cam", "");

      return {
        ...current,
        cameras: [
          ...current.cameras,
          {
            key,
            name: `Camera ${number}`,
            enabled: true,
            source_type: "rtsp",
            host: "",
            stream_path: "/stream",
            control_port: 8080,
            stream_url: "",
          },
        ],
      };
    });
  }

  function removeCamera(index) {
    setSettings((current) => ({
      ...current,
      cameras: current.cameras.filter(
        (_camera, cameraIndex) => cameraIndex !== index,
      ),
    }));
  }

  useEffect(() => {
    loadSettings();
    loadCredentialsStatus();
    refreshStatus();
    refreshPresetStatus();

    const recordingInterval =
      window.setInterval(
        refreshStatus,
        3000,
      );

    const presetInterval =
      window.setInterval(
        refreshPresetStatus,
        30000,
      );

    return () => {
      window.clearInterval(
        recordingInterval,
      );
      window.clearInterval(
        presetInterval,
      );
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
            Camera recording and configuration.
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

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <CapabilityCard
          label="GStreamer"
          description="Needed for ESP32-CAM cameras"
          available={status?.gstreamer_available}
          detail={status?.gstreamer_error}
        />

        <CapabilityCard
          label="ffmpeg"
          description="Needed for RTSP cameras"
          available={status?.ffmpeg_available}
          detail={
            status && !status.ffmpeg_available
              ? "Install on the Pi with: sudo apt-get install ffmpeg"
              : null
          }
        />
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

        <NumberSetting
          label="Frame rate (ESP32-CAM only)"
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
          label="Video bitrate (ESP32-CAM only)"
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
          label="Segments waiting for upload, per camera"
          value={settings.pending_upload_limit}
          suffix="max"
          min={1}
          onChange={(value) =>
            updateSetting(
              "pending_upload_limit",
              value,
            )
          }
        />

        <label className="rounded-2xl bg-slate-50 p-4 md:col-span-2 lg:col-span-3">
          <span className="text-sm font-medium text-slate-700">
            Temporary recording directory (RAM)
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
              Day / Night Presets (ESP32-CAM only)
            </h3>

            <p className="mt-1 text-sm text-slate-500">
              ESP32-CAM cameras automatically switch
              presets according to these times. RTSP
              cameras handle day and night themselves.
            </p>
          </div>

          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
            Checks every{" "}
            {Math.round(
              (presetStatus?.check_interval_seconds ??
                1800) / 60,
            )}{" "}
            minutes
          </span>
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <TimeSetting
            label="Day preset time"
            value={settings.day_mode_time}
            onChange={(value) =>
              updateSetting(
                "day_mode_time",
                value,
              )
            }
          />

          <TimeSetting
            label="Night preset time"
            value={settings.night_mode_time}
            onChange={(value) =>
              updateSetting(
                "night_mode_time",
                value,
              )
            }
          />
        </div>

        <p className="mt-4 text-xs text-slate-500">
          Timezone:{" "}
          <span className="font-medium">
            {presetStatus?.timezone ??
              "Asia/Kolkata"}
          </span>
          . Failed camera requests are ignored and
          retried at the next scheduled check.
        </p>
      </div>

      <div className="mt-6 rounded-2xl border border-slate-200 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold text-slate-950">
              Backblaze B2
            </h3>

            <p className="mt-1 text-sm text-slate-500">
              Upload completed CCTV segments to
              Backblaze B2. Each segment is uploaded
              once and then deleted, whether or not
              the upload succeeded.
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

        <div className="mt-5 grid gap-4 md:grid-cols-3">
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
            label="Bucket"
            value={settings.b2_bucket}
            mono
            placeholder="Bucket name from the Backblaze console"
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

      <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-semibold text-slate-950">
          Cameras
        </h3>

        <button
          type="button"
          onClick={addCamera}
          disabled={pending !== null}
          className="flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800 disabled:opacity-50"
        >
          <Plus size={17} />
          Add Camera
        </button>
      </div>

      <div className="mt-4 grid gap-5 lg:grid-cols-2">
        {settings.cameras.map(
          (camera, index) => {
            const cameraStatus =
              status?.cameras?.find(
                (item) =>
                  item.key === camera.key,
              );

            const cameraPreset =
              presetStatus?.cameras?.find(
                (item) =>
                  item.key === camera.key,
              );

            const isEsp32 =
              camera.source_type === "esp32_mjpeg";

            const toolMissing =
              status &&
              (isEsp32
                ? !status.gstreamer_available
                : !status.ffmpeg_available);

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

                {isEsp32 && (
                  <div className="mt-4 rounded-xl bg-slate-50 p-3">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-xs font-semibold text-slate-600">
                        Current applied preset
                      </span>

                      <span
                        className={`rounded-full px-3 py-1 text-xs font-semibold ${
                          cameraPreset?.preset === "day"
                            ? "bg-amber-100 text-amber-700"
                            : cameraPreset?.preset === "night"
                              ? "bg-indigo-100 text-indigo-700"
                              : "bg-slate-200 text-slate-600"
                        }`}
                      >
                        {cameraPreset?.preset === "day"
                          ? "Day"
                          : cameraPreset?.preset === "night"
                            ? "Night"
                            : "Unknown"}
                      </span>
                    </div>

                    {cameraPreset?.applied_at && (
                      <div className="mt-2 text-xs text-slate-500">
                        Last successfully applied:{" "}
                        {new Date(
                          cameraPreset.applied_at,
                        ).toLocaleString()}
                      </div>
                    )}
                  </div>
                )}

                {!isEsp32 && cameraStatus?.video_codec && (
                  <div className="mt-4 rounded-xl bg-slate-50 p-3 text-xs text-slate-600">
                    Video:{" "}
                    <span className="font-mono font-semibold">
                      {cameraStatus.video_codec}
                    </span>
                    {" "}(copied, not re-encoded). Audio:{" "}
                    <span className="font-mono font-semibold">
                      {cameraStatus.audio_codec ?? "none"}
                    </span>
                  </div>
                )}

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

                  <label className="block">
                    <span className="text-sm font-medium text-slate-700">
                      Camera type
                    </span>

                    <select
                      value={camera.source_type}
                      onChange={(event) =>
                        updateCamera(
                          index,
                          "source_type",
                          event.target.value,
                        )
                      }
                      className="mt-2 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm"
                    >
                      {SOURCE_TYPES.map((type) => (
                        <option
                          key={type.value}
                          value={type.value}
                        >
                          {type.label}
                        </option>
                      ))}
                    </select>
                  </label>

                  {isEsp32 ? (
                    <>
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
                    </>
                  ) : (
                    <div>
                      <TextField
                        label="RTSP stream URL"
                        value={camera.stream_url}
                        mono
                        placeholder="rtsp://user:password@192.168.1.18:554/ch0_0.264"
                        onChange={(value) =>
                          updateCamera(
                            index,
                            "stream_url",
                            value,
                          )
                        }
                      />

                      <p className="mt-2 text-xs text-slate-500">
                        Include the camera login in the URL
                        if it needs one. It is stored only on
                        the Raspberry Pi. Pick the main or sub
                        stream here to control file size.
                      </p>
                    </div>
                  )}
                </div>

                {toolMissing && (
                  <div className="mt-4 rounded-xl bg-amber-50 p-3 text-xs text-amber-700">
                    {isEsp32
                      ? "GStreamer is not available on the Pi, so this camera cannot record."
                      : "ffmpeg is not available on the Pi, so this camera cannot record."}
                  </div>
                )}

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

                <button
                  type="button"
                  onClick={() => removeCamera(index)}
                  disabled={pending !== null}
                  className="mt-5 flex items-center gap-2 rounded-xl border border-red-200 bg-white px-3 py-2 text-xs font-semibold text-red-700 disabled:opacity-50"
                >
                  <Trash2 size={15} />
                  Remove camera
                </button>
              </div>
            );
          },
        )}
      </div>

      <p className="mt-3 text-xs text-slate-500">
        Camera changes take effect after Save Settings
        and the next recording start.
      </p>

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
            anyRecording
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


function CapabilityCard({
  label,
  description,
  available,
  detail,
}) {
  return (
    <div className="rounded-2xl bg-slate-50 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-900">
            {label}
          </div>

          <div className="mt-1 text-sm text-slate-500">
            {description}
          </div>
        </div>

        <span
          className={`rounded-full px-3 py-1 text-xs font-semibold ${
            available
              ? "bg-emerald-100 text-emerald-700"
              : "bg-red-100 text-red-700"
          }`}
        >
          {available ? "Ready" : "Not Ready"}
        </span>
      </div>

      {detail && (
        <p className="mt-3 text-xs text-red-700">
          {detail}
        </p>
      )}
    </div>
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


function TimeSetting({
  label,
  value,
  onChange,
}) {
  return (
    <label className="rounded-2xl bg-slate-50 p-4">
      <span className="text-sm font-medium text-slate-700">
        {label}
      </span>

      <input
        type="time"
        value={value}
        onChange={(event) =>
          onChange(event.target.value)
        }
        className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm"
      />
    </label>
  );
}


function TextField({
  label,
  value,
  onChange,
  mono = false,
  placeholder = "",
}) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-slate-700">
        {label}
      </span>

      <input
        type="text"
        value={value}
        placeholder={placeholder}
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
