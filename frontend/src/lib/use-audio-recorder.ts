"use client";

/**
 * Browser audio recording via the MediaRecorder API, for the Speaking practice
 * page. Records a mic clip, exposes it as a Blob (+ object URL for playback),
 * and cleans up the mic stream and object URLs on stop/reset/unmount.
 *
 * The container is chosen to be one Whisper accepts (webm, else mp4 for Safari,
 * else ogg, else the browser default); the matching file extension is exposed
 * so the caller can name the upload — the backend uses the filename to detect
 * the codec.
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

export type RecorderStatus =
  | "idle"
  | "requesting"
  | "recording"
  | "recorded"
  | "unsupported";

export type AudioRecorder = {
  status: RecorderStatus;
  /** Elapsed recording time in whole seconds. */
  seconds: number;
  /** The recorded clip, once stopped. */
  blob: Blob | null;
  /** Object URL for playing the recorded clip back. */
  url: string | null;
  /** Suggested upload filename, e.g. "recording.webm". */
  filename: string | null;
  /** Human-readable error (e.g. microphone permission denied). */
  error: string | null;
  start: () => Promise<void>;
  stop: () => void;
  reset: () => void;
};

/** Whether this browser can record audio at all. */
function isSupported(): boolean {
  return (
    typeof MediaRecorder !== "undefined" &&
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia
  );
}

// Support never changes for a given page load, so the store never notifies.
const noopSubscribe = () => () => {};

/** First Whisper-friendly container the browser can record, or undefined. */
function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  for (const type of ["audio/webm", "audio/mp4", "audio/ogg"]) {
    if (MediaRecorder.isTypeSupported(type)) return type;
  }
  return undefined; // let the browser pick its default
}

function extensionFor(mimeType: string): string {
  if (mimeType.includes("webm")) return "webm";
  if (mimeType.includes("mp4")) return "mp4";
  if (mimeType.includes("ogg")) return "ogg";
  if (mimeType.includes("mpeg") || mimeType.includes("mp3")) return "mp3";
  if (mimeType.includes("wav")) return "wav";
  return "webm";
}

export function useAudioRecorder(): AudioRecorder {
  const [status, setStatus] = useState<RecorderStatus>("idle");
  const [seconds, setSeconds] = useState(0);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [filename, setFilename] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const urlRef = useRef<string | null>(null);

  // Capability probe without an effect (avoids setState-in-effect / hydration
  // mismatch): assume supported on the server, read the real value on the client.
  const supported = useSyncExternalStore(noopSubscribe, isSupported, () => true);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const releaseStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const revokeUrl = useCallback(() => {
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
  }, []);

  const start = useCallback(async () => {
    if (!supported) return;
    setError(null);
    // Drop any previous take.
    revokeUrl();
    setUrl(null);
    setBlob(null);
    setFilename(null);
    setSeconds(0);
    setStatus("requesting");

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      const denied =
        err instanceof DOMException &&
        (err.name === "NotAllowedError" || err.name === "SecurityError");
      setError(
        denied
          ? "Microphone access was denied. Allow it in your browser to record."
          : err instanceof Error
            ? err.message
            : String(err),
      );
      setStatus("idle");
      return;
    }

    streamRef.current = stream;
    const mimeType = pickMimeType();
    const recorder = mimeType
      ? new MediaRecorder(stream, { mimeType })
      : new MediaRecorder(stream);
    recorderRef.current = recorder;
    chunksRef.current = [];

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunksRef.current.push(event.data);
    };
    recorder.onstop = () => {
      const type = recorder.mimeType || mimeType || "audio/webm";
      const recorded = new Blob(chunksRef.current, { type });
      const objectUrl = URL.createObjectURL(recorded);
      urlRef.current = objectUrl;
      setBlob(recorded);
      setUrl(objectUrl);
      setFilename(`recording.${extensionFor(type)}`);
      setStatus("recorded");
      clearTimer();
      releaseStream();
    };

    recorder.start();
    setStatus("recording");
    timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
  }, [supported, revokeUrl, clearTimer, releaseStream]);

  const stop = useCallback(() => {
    clearTimer();
    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      recorderRef.current.stop(); // onstop builds the blob + releases the mic
    }
  }, [clearTimer]);

  const reset = useCallback(() => {
    clearTimer();
    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      recorderRef.current.onstop = null;
      recorderRef.current.stop();
    }
    releaseStream();
    revokeUrl();
    recorderRef.current = null;
    chunksRef.current = [];
    setBlob(null);
    setUrl(null);
    setFilename(null);
    setSeconds(0);
    setError(null);
    setStatus("idle");
  }, [clearTimer, releaseStream, revokeUrl]);

  // Tear everything down if the component unmounts mid-recording.
  useEffect(() => {
    return () => {
      clearTimer();
      streamRef.current?.getTracks().forEach((track) => track.stop());
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    };
  }, [clearTimer]);

  return {
    status: supported ? status : "unsupported",
    seconds,
    blob,
    url,
    filename,
    error,
    start,
    stop,
    reset,
  };
}
