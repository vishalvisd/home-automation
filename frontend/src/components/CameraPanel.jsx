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
  flushArchive,
  getArchiveStatus,
  getBackblazeAccounts,
  getBackblazeRotation,
  getCameraSettings,
  getPresetStatus,
  getRecordingStatus,
  saveBackblazeAccounts,
  testBackblazeAccount,
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


const SECTIONS = [
  ["cameras", "Cameras"],
  ["disk", "Disk copy"],
  ["cloud", "Cloud (Backblaze)"],
  ["settings", "Recording settings"],
];

const SECTION_STORAGE_KEY = "cctvSection";

function loadSection() {
  try {
    const stored = localStorage.getItem(SECTION_STORAGE_KEY);
    return SECTIONS.some(([key]) => key === stored) ? stored : "cameras";
  } catch {
    return "cameras";
  }
}


export default function CameraPanel() {
  const [settings, setSettings] = useState(null);
  const [status, setStatus] = useState(null);
  const [presetStatus, setPresetStatus] =
    useState(null);
  const [pending, setPending] = useState(null);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);
  // Backblaze accounts as edited in the table. application_key is
  // always empty when loaded from the Pi (it never returns secrets);
  // typing one replaces the stored key on save.
  const [accounts, setAccounts] = useState(null);
  const [rotation, setRotation] = useState(null);
  // Result of the last Test per account row, keyed by row index.
  const [accountTests, setAccountTests] = useState({});
  const [archive, setArchive] = useState(null);
  const [section, setSection] = useState(() => loadSection());

  async function loadSettings() {
    try {
      setSettings(await getCameraSettings());
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  function accountsFromStatus(status) {
    return status.accounts.map((account) => ({
      ...account,
      application_key: "",
      stored: true,
    }));
  }

  async function loadAccounts() {
    try {
      setAccounts(
        accountsFromStatus(await getBackblazeAccounts()),
      );
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function refreshArchive() {
    try {
      setArchive(await getArchiveStatus());
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function runArchiveBatch() {
    setPending("archive");
    setMessage(null);
    setError(null);

    try {
      setArchive(await flushArchive());
      setMessage("Disk batch finished.");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setPending(null);
    }
  }

  async function loadRotation() {
    try {
      setRotation(await getBackblazeRotation());
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

  async function saveAccounts() {
    setPending("accounts");
    setMessage(null);
    setError(null);

    try {
      const result = await saveBackblazeAccounts(
        accounts.map((account) => ({
          name: account.name,
          key_id: account.key_id,
          application_key: account.application_key,
          bucket: account.bucket,
          enabled: account.enabled,
        })),
      );

      // Never retain application keys in browser state after
      // they have been saved.
      setAccounts(accountsFromStatus(result));
      await loadRotation();

      setMessage("Backblaze accounts saved.");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setPending(null);
    }
  }

  async function testAccount(index) {
    const account = accounts[index];

    setAccountTests((current) => ({
      ...current,
      [index]: { pending: true },
    }));

    try {
      const result = await testBackblazeAccount({
        name: account.name,
        key_id: account.key_id,
        application_key: account.application_key,
        bucket: account.bucket,
        enabled: account.enabled,
      });

      setAccountTests((current) => ({
        ...current,
        [index]: result,
      }));
    } catch (requestError) {
      setAccountTests((current) => ({
        ...current,
        [index]: { ok: false, detail: requestError.message },
      }));
    }
  }

  function chooseSection(value) {
    setSection(value);
    try {
      localStorage.setItem(SECTION_STORAGE_KEY, value);
    } catch {
      // not remembered, that is all
    }
  }

  function updateAccount(index, key, value) {
    setAccounts((current) =>
      current.map((account, accountIndex) =>
        accountIndex === index
          ? { ...account, [key]: value }
          : account,
      ),
    );
  }

  function addAccount() {
    setAccounts((current) => [
      ...(current ?? []),
      {
        name: "",
        key_id: "",
        application_key: "",
        bucket: "",
        enabled: true,
        stored: false,
      },
    ]);
  }

  function removeAccount(index) {
    setAccounts((current) =>
      current.filter((_account, accountIndex) => accountIndex !== index),
    );
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
            sub_stream_url: "",
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
    loadAccounts();
    loadRotation();
    refreshStatus();
    refreshPresetStatus();
    refreshArchive();

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

    const archiveInterval =
      window.setInterval(
        refreshArchive,
        15000,
      );

    return () => {
      window.clearInterval(
        recordingInterval,
      );
      window.clearInterval(
        presetInterval,
      );
      window.clearInterval(
        archiveInterval,
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

      <nav className="mt-6 overflow-x-auto" aria-label="CCTV sections">
        <div className="flex min-w-max gap-1 rounded-2xl bg-slate-100 p-1" role="tablist">
          {SECTIONS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={section === key}
              onClick={() => chooseSection(key)}
              className={`whitespace-nowrap rounded-xl px-4 py-2 text-sm font-semibold transition ${
                section === key
                  ? "bg-white text-slate-950 shadow-sm"
                  : "text-slate-600 hover:text-slate-950"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </nav>

      <div className={section === "settings" ? "" : "hidden"}>
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

      </div>

      <div className={section === "disk" ? "" : "hidden"}>
      <div className="mt-6 rounded-2xl border border-slate-200 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold text-slate-950">
              Disk copy on the USB disk (primary recording)
            </h3>

            <p className="mt-1 text-sm text-slate-500">
              The primary recording: full-quality main-stream clips are
              buffered in RAM and moved to the disk in batches. The disk
              is parked between batches. When free space runs low the
              oldest day is deleted.
            </p>
          </div>

          <span
            className={`rounded-full px-3 py-1 text-xs font-semibold ${
              !settings.archive_enabled
                ? "bg-slate-100 text-slate-600"
                : archive?.last_error
                  ? "bg-red-100 text-red-700"
                  : archive?.disk_present
                    ? "bg-emerald-100 text-emerald-700"
                    : "bg-amber-100 text-amber-700"
            }`}
          >
            {!settings.archive_enabled
              ? "Disk copy off"
              : archive?.last_error
                ? "Disk copy error"
                : archive?.disk_present
                  ? archive?.mounted
                    ? "Disk awake, batch running"
                    : archive?.parked
                      ? "Disk parked"
                      : "Disk present"
                  : "Disk not plugged in"}
          </span>
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-3">
          <label className="rounded-2xl bg-slate-50 p-4">
            <span className="text-sm font-medium text-slate-700">
              Disk copy enabled
            </span>

            <div className="mt-3 flex items-center gap-3">
              <input
                type="checkbox"
                checked={settings.archive_enabled}
                onChange={(event) =>
                  updateSetting("archive_enabled", event.target.checked)
                }
                className="h-5 w-5"
              />

              <span className="text-sm">
                {settings.archive_enabled ? "Enabled" : "Disabled"}
              </span>
            </div>
          </label>

          <NumberSetting
            label="Batch every"
            value={settings.archive_flush_minutes}
            suffix="minutes"
            min={1}
            onChange={(value) =>
              updateSetting("archive_flush_minutes", value)
            }
          />

          <NumberSetting
            label="RAM buffer limit"
            value={settings.archive_buffer_limit_mb}
            suffix="MB"
            min={50}
            onChange={(value) =>
              updateSetting("archive_buffer_limit_mb", value)
            }
          />

          <NumberSetting
            label="Keep at least this much free"
            value={settings.archive_min_free_gb}
            suffix="GB"
            min={1}
            onChange={(value) =>
              updateSetting("archive_min_free_gb", value)
            }
          />

          <TextField
            label="Disk mount folder"
            value={settings.archive_directory}
            mono
            onChange={(value) => updateSetting("archive_directory", value)}
          />

          <TextField
            label="Disk device"
            value={settings.archive_disk_device}
            mono
            onChange={(value) =>
              updateSetting("archive_disk_device", value)
            }
          />
        </div>

        {archive && (
          <div className="mt-4 grid gap-3 text-xs text-slate-600 md:grid-cols-2">
            <div className="rounded-xl bg-slate-50 p-3">
              <div>
                Waiting in RAM:{" "}
                <span className="font-semibold text-slate-800">
                  {archive.waiting_files} clip(s), {archive.waiting_mb} MB
                </span>
              </div>
              <div>
                Last batch:{" "}
                <span className="font-semibold text-slate-800">
                  {archive.last_flush_at
                    ? `${archive.last_flush_at.slice(0, 16).replace("T", " ")}, ${archive.last_flush_files} clip(s), ${archive.last_flush_mb} MB`
                    : "none yet"}
                </span>
              </div>
              {archive.disk?.total_gb != null && (
                <div>
                  Disk:{" "}
                  <span className="font-semibold text-slate-800">
                    {archive.disk.free_gb} GB free of {archive.disk.total_gb} GB,
                    {" "}{archive.disk.days} day(s) kept
                    {archive.disk.oldest_day
                      ? `, oldest ${archive.disk.oldest_day}`
                      : ""}
                  </span>
                </div>
              )}
            </div>

            <div className="rounded-xl bg-slate-50 p-3">
              <div className="font-semibold text-slate-800">Disk health (SMART)</div>
              {archive.smart?.error ? (
                <div className="text-amber-700">{archive.smart.error}</div>
              ) : archive.smart?.read_at ? (
                <div>
                  reallocated {archive.smart.reallocated_sectors ?? "?"},
                  pending {archive.smart.pending_sectors ?? "?"},
                  uncorrectable {archive.smart.uncorrectable_sectors ?? "?"},
                  {" "}{archive.smart.power_on_hours ?? "?"} h on,
                  {" "}{archive.smart.start_stop_count ?? "?"} starts,
                  {" "}{archive.smart.temperature_c ?? "?"} °C
                  <span className="text-slate-400">
                    {" "}(read {archive.smart.read_at.slice(0, 16).replace("T", " ")})
                  </span>
                </div>
              ) : (
                <div>Read during the next batch.</div>
              )}
            </div>
          </div>
        )}

        {archive?.last_error && (
          <div className="mt-3 rounded-xl bg-red-50 p-3 text-xs text-red-700">
            {archive.last_error}
          </div>
        )}

        <button
          type="button"
          onClick={runArchiveBatch}
          disabled={pending !== null || !settings.archive_enabled}
          className="mt-4 flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800 disabled:opacity-50"
        >
          {pending === "archive" ? (
            <LoaderCircle size={16} className="animate-spin" />
          ) : null}
          Run a batch now
        </button>

        <p className="mt-3 text-xs text-slate-500">
          Changing the disk copy setting takes effect after Save Settings
          and the next Stop / Start Recording.
        </p>
      </div>

      </div>

      <div className={section === "cloud" ? "" : "hidden"}>
      <div className="mt-6 rounded-2xl border border-slate-200 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold text-slate-950">
              Backblaze B2
            </h3>

            <p className="mt-1 text-sm text-slate-500">
              Completed segments are uploaded once and then
              deleted, whether or not the upload succeeded. Each
              calendar day goes to one account; the next day takes
              the next enabled account in the list.
            </p>
          </div>

          <span
            className={`rounded-full px-3 py-1 text-xs font-semibold ${
              accounts?.some((account) => account.stored && account.enabled)
                ? "bg-emerald-100 text-emerald-700"
                : "bg-amber-100 text-amber-700"
            }`}
          >
            {accounts?.some((account) => account.stored && account.enabled)
              ? `${accounts.filter((account) => account.enabled).length} account(s) enabled`
              : "No account configured"}
          </span>
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-2">
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

          <NumberSetting
            label="Upload speed limit, shared by all uploads"
            value={settings.b2_upload_rate_kb_s}
            suffix="KB/s"
            min={1}
            onChange={(value) =>
              updateSetting(
                "b2_upload_rate_kb_s",
                value,
              )
            }
          />
        </div>

        {rotation && (
          <div className="mt-4 rounded-xl bg-slate-50 p-4 text-xs text-slate-600">
            <span className="font-semibold text-slate-800">
              Today ({rotation.today}):
            </span>{" "}
            {rotation.today_account
              ? `uploading to "${rotation.today_account}"`
              : "no clip uploaded yet today; the next one picks the account"}
            {Object.keys(rotation.days).length > 0 && (
              <span className="ml-2 text-slate-500">
                Recent days:{" "}
                {Object.entries(rotation.days)
                  .slice(-7)
                  .map(([day, name]) => `${day.slice(5)} → ${name}`)
                  .join(", ")}
              </span>
            )}
          </div>
        )}

        <div className="mt-5 border-t border-slate-200 pt-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-slate-900">
                Accounts
              </div>

              <p className="mt-1 text-xs text-slate-500">
                Keys are stored only on this Raspberry Pi. Leave
                the application key empty to keep the one already
                stored.
              </p>
            </div>

            <button
              type="button"
              onClick={addAccount}
              disabled={pending !== null}
              className="flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800 disabled:opacity-50"
            >
              <Plus size={17} />
              Add Account
            </button>
          </div>

          <div className="mt-4 space-y-4">
            {(accounts ?? []).map((account, index) => (
              <div
                key={index}
                className="rounded-2xl bg-slate-50 p-4"
              >
                <div className="grid gap-3 md:grid-cols-2">
                  <TextField
                    label="Name"
                    value={account.name}
                    placeholder="eu-06"
                    onChange={(value) =>
                      updateAccount(index, "name", value)
                    }
                  />

                  <TextField
                    label="Bucket"
                    value={account.bucket}
                    mono
                    placeholder="visd-cctv-eu-06"
                    onChange={(value) =>
                      updateAccount(index, "bucket", value)
                    }
                  />

                  <TextField
                    label="Application Key ID"
                    value={account.key_id}
                    mono
                    placeholder="003..."
                    onChange={(value) =>
                      updateAccount(index, "key_id", value)
                    }
                  />

                  <label className="block">
                    <span className="text-sm font-medium text-slate-700">
                      Application Key
                    </span>

                    <input
                      type="password"
                      value={account.application_key}
                      autoComplete="new-password"
                      onChange={(event) =>
                        updateAccount(
                          index,
                          "application_key",
                          event.target.value,
                        )
                      }
                      placeholder={
                        account.stored
                          ? "Stored on the Pi; enter only to replace"
                          : "Enter Application Key"
                      }
                      className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 font-mono text-sm"
                    />
                  </label>
                </div>

                <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={account.enabled}
                      onChange={(event) =>
                        updateAccount(
                          index,
                          "enabled",
                          event.target.checked,
                        )
                      }
                      className="h-4 w-4"
                    />
                    Enabled (takes part in the rotation)
                  </label>

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => testAccount(index)}
                      disabled={
                        pending !== null ||
                        accountTests[index]?.pending ||
                        !account.key_id.trim() ||
                        !account.bucket.trim() ||
                        (!account.stored && !account.application_key.trim())
                      }
                      className="flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-800 disabled:opacity-50"
                    >
                      {accountTests[index]?.pending ? (
                        <LoaderCircle size={14} className="animate-spin" />
                      ) : null}
                      Test
                    </button>

                    <button
                      type="button"
                      onClick={() => removeAccount(index)}
                      disabled={pending !== null}
                      className="flex items-center gap-2 rounded-xl border border-red-200 px-3 py-1.5 text-xs font-semibold text-red-700 disabled:opacity-50"
                    >
                      <Trash2 size={14} />
                      Remove account
                    </button>
                  </div>
                </div>

                {accountTests[index] && !accountTests[index].pending && (
                  <div
                    className={`mt-3 rounded-xl p-3 text-xs ${
                      accountTests[index].ok
                        ? "bg-emerald-50 text-emerald-700"
                        : "bg-red-50 text-red-700"
                    }`}
                  >
                    {accountTests[index].detail}
                  </div>
                )}
              </div>
            ))}
          </div>

          <button
            type="button"
            onClick={saveAccounts}
            disabled={pending !== null || accounts === null}
            className="mt-4 flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-3 text-sm font-semibold text-white disabled:opacity-50"
          >
            <Save size={17} />
            Save Accounts
          </button>
        </div>
      </div>

      </div>

      <div className={section === "cameras" ? "" : "hidden"}>
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

                      <div className="mt-4">
                        <TextField
                          label="Sub stream URL for the cloud copy (optional)"
                          value={camera.sub_stream_url ?? ""}
                          mono
                          placeholder="rtsp://user:password@192.168.1.18:554/ch0_1.264"
                          onChange={(value) =>
                            updateCamera(
                              index,
                              "sub_stream_url",
                              value,
                            )
                          }
                        />

                        <p className="mt-2 text-xs text-slate-500">
                          When set, the clips uploaded to Backblaze
                          come from this smaller stream. The disk copy
                          and Live View always use the main stream
                          above. Leave empty to upload the main stream.
                        </p>
                      </div>
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

                {cameraStatus && !isEsp32 && (
                  <>
                    <CopyStatus
                      title="Disk copy"
                      subtitle="primary, full quality"
                      kind="disk"
                      recorder={cameraStatus.disk}
                      store={cameraStatus.disk?.store}
                      segmentSeconds={settings.segment_seconds}
                    />
                    <CopyStatus
                      title="Cloud copy"
                      subtitle="backup, sub stream"
                      kind="cloud"
                      recorder={cameraStatus}
                      store={cameraStatus.upload}
                      segmentSeconds={settings.segment_seconds}
                    />
                  </>
                )}

                {cameraStatus && isEsp32 && (
                  <CopyStatus
                    title="Cloud copy"
                    subtitle="ESP32-CAM"
                    kind="cloud"
                    recorder={cameraStatus}
                    store={cameraStatus.upload}
                    segmentSeconds={settings.segment_seconds}
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



// ---------------------------------------------------------------------
// Per-copy status on the camera card: a light, plain-language lines and
// a strip of the last 24 hours. Everything comes from the status API,
// which reads memory only.
// ---------------------------------------------------------------------

function minutesSince(iso) {
  if (!iso) return null;
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return null;
  return Math.max(0, (Date.now() - then) / 60000);
}

function ago(iso) {
  const minutes = minutesSince(iso);
  if (minutes == null) return "never";
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${Math.round(minutes)} min ago`;
  const hours = minutes / 60;
  if (hours < 48) return `${Math.floor(hours)} h ${Math.round(minutes % 60)} min ago`;
  return `${Math.round(hours / 24)} days ago`;
}

function clock(iso) {
  return iso ? iso.slice(11, 16) : "";
}

function megabytes(bytes) {
  return bytes == null ? "" : `${(bytes / 1e6).toFixed(1)} MB`;
}

function copyLight(recorder, store, kind, segmentSeconds) {
  if (!recorder) return ["slate", "not configured"];

  const clipLate = minutesSince(recorder.last_completed_at ?? recorder.started_at);
  const staleAfter = (2 * segmentSeconds) / 60 + 1;
  const recentRecovery = minutesSince(recorder.last_recovery_at) < 10;

  if (!recorder.running) return ["red", recorder.last_error ? "recorder stopped with an error" : "recorder not running"];

  if (kind === "cloud") {
    if (store.last_failure_at && (!store.last_upload_at || store.last_failure_at > store.last_upload_at)) {
      return ["red", "last upload failed"];
    }
    if (minutesSince(store.last_failure_at) < 10) return ["amber", "an upload failed recently"];
  } else {
    if (store.last_error && store.waiting_files > 0) return ["amber", "disk problem, clips waiting in RAM"];
    if (store.dropped > 0 && minutesSince(store.last_batch_at) > 35) return ["red", "clips are being dropped"];
    if (store.last_batch_at && minutesSince(store.last_batch_at) > 40 && store.waiting_files > 0) return ["amber", "disk batch is late"];
  }

  if (!recorder.stream_connected) return ["amber", "reconnecting to the camera"];
  if (clipLate != null && clipLate > staleAfter) return ["amber", "no clip closed recently"];
  if (recentRecovery) return ["amber", "recovered a moment ago"];
  return ["green", "recording"];
}

const LIGHT_CLASSES = {
  green: "bg-emerald-500",
  amber: "bg-amber-400",
  red: "bg-red-500",
  slate: "bg-slate-300",
};

const HOUR_CLASSES = {
  green: "bg-emerald-500",
  amber: "bg-amber-400",
  red: "bg-red-500",
  unknown: "bg-slate-200",
};

function hourColour(hour, expected) {
  if (!hour.known) return "unknown";
  // The running hour is judged on what it could have produced so far.
  const minutesIntoHour = hour.current ? new Date().getMinutes() + 1 : 60;
  const possible = Math.max(1, Math.round((expected * minutesIntoHour) / 60));
  const ratio = hour.count / possible;
  if (ratio >= 0.9) return "green";
  if (ratio >= 0.5) return "amber";
  return "red";
}

function HourStrip({ hours, expected }) {
  if (!hours || hours.length === 0) return null;

  return (
    <div className="mt-2 flex items-center gap-[3px]" title="Last 24 hours, newest on the right">
      {hours.map((hour) => (
        <span
          key={hour.hour}
          className={`h-3 flex-1 rounded-[2px] ${HOUR_CLASSES[hourColour(hour, expected)]}`}
          title={`${hour.hour.slice(5, 16).replace("T", " ")}: ${hour.count} clip(s), ${megabytes(hour.bytes)}${hour.known ? "" : " (no data)"}`}
        />
      ))}
    </div>
  );
}

function CopyStatus({ title, subtitle, recorder, store, kind, segmentSeconds }) {
  const [light, reason] = copyLight(recorder, store ?? {}, kind, segmentSeconds);
  const expected = Math.max(1, Math.round(3600 / segmentSeconds));
  const stream = recorder
    ? [
        recorder.width && recorder.height ? `${recorder.width}x${recorder.height}` : null,
        recorder.video_codec,
        recorder.audio_codec ? "audio" : "no audio",
      ].filter(Boolean).join(" ")
    : "";

  return (
    <div className="mt-3 rounded-xl bg-slate-50 p-3 text-xs text-slate-600">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`inline-block h-3 w-3 rounded-full ${LIGHT_CLASSES[light]}`} />
        <span className="font-semibold text-slate-900">{title}</span>
        <span className="text-slate-500">{subtitle}</span>
        <span className="ml-auto text-slate-500">{reason}</span>
      </div>

      {recorder && (
        <div className="mt-2 space-y-1">
          <div>
            {recorder.stream_connected
              ? `Connected ${ago(recorder.connected_at)}`
              : recorder.running
                ? "Reconnecting"
                : "Stopped"}
            {stream ? ` · ${stream}` : ""}
          </div>

          <div>
            {recorder.current_fragment_started_at
              ? `Recording a clip since ${clock(recorder.current_fragment_started_at)} (${ago(recorder.current_fragment_started_at)})`
              : "No clip in progress"}
            {recorder.last_completed_at
              ? ` · last clip closed ${ago(recorder.last_completed_at)}, ${megabytes(recorder.last_completed_bytes)}${
                  recorder.last_completed_duration ? `, ${Math.round(recorder.last_completed_duration)} s` : ""
                }`
              : " · no clip closed yet"}
          </div>

          {kind === "cloud" && store && (
            <div>
              {store.last_upload_at
                ? `Uploaded ${ago(store.last_upload_at)} to ${store.last_upload_account}, ${megabytes(store.last_upload_bytes)}`
                : "Nothing uploaded yet"}
              {` · since start: ${store.uploads_ok} uploaded, ${store.uploads_failed} failed`}
              {store.dropped > 0 ? `, ${store.dropped} dropped` : ""}
              {store.waiting_files > 0 ? ` · ${store.waiting_files} waiting` : ""}
            </div>
          )}

          {kind === "disk" && store && (
            <div>
              {store.waiting_files > 0
                ? `Waiting for the disk batch: ${store.waiting_files} clip(s), ${megabytes(store.waiting_bytes)}`
                : "Nothing waiting for the disk"}
              {store.last_stored_at
                ? ` · last stored ${ago(store.last_stored_at)}`
                : " · nothing stored yet"}
              {store.last_batch_at ? ` · last batch ${ago(store.last_batch_at)}` : ""}
              {` · since start: ${store.stored_ok} stored${store.stored_failed ? `, ${store.stored_failed} failed` : ""}${store.dropped ? `, ${store.dropped} dropped` : ""}`}
            </div>
          )}

          {recorder.restart_count > 0 && (
            <div className="text-amber-700">
              Recoveries: {recorder.restart_count}
              {recorder.last_recovery_at ? `, last ${ago(recorder.last_recovery_at)}` : ""}
            </div>
          )}

          {(recorder.last_error || (kind === "cloud" && store?.last_failure) || (kind === "disk" && store?.last_error)) && (
            <div className="text-red-700">
              {recorder.last_error
                ? `${recorder.last_error}${recorder.last_error_at ? ` (${ago(recorder.last_error_at)})` : ""}`
                : kind === "cloud"
                  ? `Upload: ${store.last_failure} (${ago(store.last_failure_at)})`
                  : `Disk: ${store.last_error}`}
            </div>
          )}
        </div>
      )}

      <HourStrip hours={recorder?.hours} expected={expected} />
    </div>
  );
}
