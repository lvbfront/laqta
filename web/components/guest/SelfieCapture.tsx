"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLocale } from "@/components/LocaleProvider";

type CameraStatus = "starting" | "active" | "unavailable";

const VIDEO_CONSTRAINTS: MediaStreamConstraints = {
  video: { facingMode: "user", width: { ideal: 720 }, height: { ideal: 960 } },
  audio: false,
};

export function SelfieCapture({ onCapture, onBack }: { onCapture: (blob: Blob) => void; onBack: () => void }) {
  const { t } = useLocale();
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [cameraStatus, setCameraStatus] = useState<CameraStatus>("starting");
  const [capturedBlob, setCapturedBlob] = useState<Blob | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  const stopCamera = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  const startCamera = useCallback(async () => {
    // Older phones / browsers without getUserMedia (or a non-HTTPS
    // context, where browsers refuse it entirely) fall back to a plain
    // file picker below -- this is that fallback's trigger condition.
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraStatus("unavailable");
      return;
    }
    setCameraStatus("starting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia(VIDEO_CONSTRAINTS);
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      setCameraStatus("active");
    } catch {
      // Permission denied, no camera, or any other getUserMedia failure --
      // all land on the same file-upload fallback rather than a dead end.
      setCameraStatus("unavailable");
    }
  }, []);

  useEffect(() => {
    startCamera();
    return () => stopCamera();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  function capture() {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    // Mirror horizontally to match the (mirrored) live preview the guest
    // was just looking at -- otherwise the captured photo looks
    // "backwards" to them, even though detection doesn't care either way.
    ctx.translate(canvas.width, 0);
    ctx.scale(-1, 1);
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(
      (blob) => {
        if (!blob) return;
        setCapturedBlob(blob);
        setPreviewUrl(URL.createObjectURL(blob));
        stopCamera();
      },
      "image/jpeg",
      0.92
    );
  }

  function retake() {
    setCapturedBlob(null);
    setPreviewUrl(null);
    startCamera();
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    stopCamera();
    setCapturedBlob(file);
    setPreviewUrl(URL.createObjectURL(file));
  }

  const showingPreview = capturedBlob !== null;

  return (
    <div className="relative flex min-h-[100dvh] flex-col bg-black">
      <button
        type="button"
        onClick={onBack}
        className="absolute top-4 start-4 z-10 rounded-full bg-black/40 px-4 py-2 text-sm font-medium text-white backdrop-blur"
      >
        {t("common.back")}
      </button>

      <div className="flex-1 relative flex items-center justify-center overflow-hidden">
        {showingPreview && previewUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={previewUrl} alt="" className="h-full w-full object-cover" />
        ) : (
          <video
            ref={videoRef}
            playsInline
            muted
            className={`h-full w-full object-cover scale-x-[-1] ${cameraStatus === "active" ? "" : "hidden"}`}
          />
        )}

        {!showingPreview && cameraStatus !== "active" && (
          <div className="flex flex-col items-center gap-4 p-6 text-center text-white">
            <p className="text-lg font-medium">{t("capture.title")}</p>
            {cameraStatus === "unavailable" && <p className="text-sm text-white/70">{t("capture.camera_unavailable")}</p>}
          </div>
        )}

        {!showingPreview && cameraStatus === "active" && (
          <div className="absolute top-6 inset-x-0 text-center px-6">
            <p className="inline-block rounded-full bg-black/40 px-4 py-2 text-sm text-white backdrop-blur">
              {t("capture.instructions")}
            </p>
          </div>
        )}
      </div>

      <canvas ref={canvasRef} className="hidden" />

      <div className="bg-black p-6 pb-8 flex flex-col items-center gap-4">
        {showingPreview ? (
          <div className="flex w-full max-w-sm gap-3">
            <button
              type="button"
              onClick={retake}
              className="flex-1 rounded-full border border-white/30 py-4 font-semibold text-white active:scale-[0.98] transition"
            >
              {t("capture.retake")}
            </button>
            <button
              type="button"
              onClick={() => capturedBlob && onCapture(capturedBlob)}
              className="flex-1 rounded-full bg-white py-4 font-semibold text-black active:scale-[0.98] transition"
            >
              {t("capture.use_photo")}
            </button>
          </div>
        ) : cameraStatus === "active" ? (
          <button
            type="button"
            onClick={capture}
            aria-label={t("capture.button")}
            className="h-20 w-20 rounded-full bg-white ring-4 ring-white/30 active:scale-95 transition"
          />
        ) : null}

        {!showingPreview && (
          <>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="text-sm font-medium text-white/80 underline underline-offset-4"
            >
              {t("capture.upload_fallback")}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              onChange={handleFileChange}
              className="hidden"
            />
          </>
        )}
      </div>
    </div>
  );
}
