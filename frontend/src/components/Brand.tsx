import { Link } from "react-router-dom";

type BrandProps = {
  audience: "customer" | "internal";
  to: string;
  tone?: "light" | "dark";
  className?: string;
};

export function Brand({ audience, to, tone = "light", className = "" }: BrandProps) {
  const context = audience === "customer" ? "客户帮助中心" : "内部工作台";
  return (
    <Link
      aria-label={"Stellogic " + context}
      className={"brand brand-" + tone + " " + className}
      to={to}
    >
      <svg aria-hidden="true" className="brand-mark" focusable="false" viewBox="0 0 40 40">
        <rect height="38" rx="12" width="38" x="1" y="1" />
        <path d="M11 24.5c4.2-1 6.2-4.2 7-9.8 5.8 1.3 9.4 4.3 11 9-3.4 2.3-7 3.3-10.8 3-2.7-.2-5.1-.9-7.2-2.2Z" />
        <path d="M14 26c3.6-4.7 7.7-7.6 12.5-8.7" />
      </svg>
      <span className="brand-copy">
        <strong>Stellogic</strong>
        <span>{context}</span>
      </span>
    </Link>
  );
}
