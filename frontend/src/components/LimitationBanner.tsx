type LimitationBannerProps = {
  text?: string;
};

export function LimitationBanner({ text }: LimitationBannerProps) {
  return (
    <section className="panel banner">
      <strong>Scientific limit</strong>
      <p>
        {text ??
          "A decoded upload is an inspected video file. It is not a completed biomechanical analysis, a 3D joint angle, or proof that the recording is side-on."}
      </p>
    </section>
  );
}
