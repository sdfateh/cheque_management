import js from "@eslint/js";
import globals from "globals";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";

export default [
	{ ignores: ["node_modules/**", "../cheque_management/public/**"] },
	js.configs.recommended,
	{
		files: ["src/**/*.{js,jsx}"],
		languageOptions: {
			ecmaVersion: 2022,
			sourceType: "module",
			globals: globals.browser,
			parserOptions: { ecmaFeatures: { jsx: true } },
		},
		plugins: { react, "react-hooks": reactHooks },
		settings: { react: { version: "detect" } },
		rules: {
			...react.configs.flat.recommended.rules,
			...reactHooks.configs.recommended.rules,
			"react/react-in-jsx-scope": "off",
			"react/prop-types": "off",
			"no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
		},
	},
	{ files: ["*.config.js"], languageOptions: { globals: globals.node } },
];
