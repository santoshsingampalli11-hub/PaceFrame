type ErrorNoticeProps = {
  message: string | null;
  id?: string;
};

export function ErrorNotice({ message, id }: ErrorNoticeProps) {
  if (!message) return null;
  return (
    <p className="error-notice" id={id} role="alert">
      {message}
    </p>
  );
}
