import "@testing-library/jest-dom/vitest";

if (typeof URL.createObjectURL !== "function") {
  URL.createObjectURL = () => "blob:frame";
}
if (typeof URL.revokeObjectURL !== "function") {
  URL.revokeObjectURL = () => undefined;
}

const motion = document.createElement("style");
motion.textContent = "*, *::before, *::after { animation: none !important; transition: none !important; }";
document.head.appendChild(motion);
