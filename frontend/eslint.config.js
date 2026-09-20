import reactHooks from "eslint-plugin-react-hooks";
import { defineConfig, globalIgnores } from "eslint/config";
import tseslint from "typescript-eslint";

export default defineConfig([
  globalIgnores(["dist"]),
  tseslint.configs.recommended,
  reactHooks.configs.flat.recommended,
]);
