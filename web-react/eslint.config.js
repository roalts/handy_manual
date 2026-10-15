import js from "@eslint/js";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { ecmaVersion: 2022, globals: globals.browser },
    plugins: { react, "react-hooks": reactHooks },
    settings: { react: { version: "19.3" } },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Answer and source text must only ever be React text children (FR-002: withheld values never displayed).
      "react/no-danger": "error",
      "react/no-danger-with-children": "error",
      "no-restricted-properties": ["error",
        { property: "innerHTML", message: "Render text as React children." },
        { property: "outerHTML", message: "Render text as React children." }],
      "no-restricted-imports": ["error", { paths: [
        { name: "streamdown", message: "Answer and source text is never rendered as markdown." },
      ] }],
    },
  },
  {
    files: ["scripts/**/*.mjs"],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.node },
  },
);
