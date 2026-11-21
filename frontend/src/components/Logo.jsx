const publicUrl = process.env.PUBLIC_URL;

export const Logo = ({ wide = false, size = 40 }) => {
  if (!wide) {
    return (
      <img src={publicUrl + "/ryziqo-icon.png"} alt="Ryziqo" width={size} height={size} className="shrink-0 rounded-sm" />
    );
  }

  return (
    <span className="relative block h-[50px] w-[246px] shrink-0 overflow-hidden">
      <img
        src={publicUrl + "/ryziqo-logo.png"}
        alt="Ryziqo"
        className="absolute left-[-22px] top-[-35px] w-[290px] max-w-none"
      />
    </span>
  );
};
