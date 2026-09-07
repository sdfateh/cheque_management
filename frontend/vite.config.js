import react from "@vitejs/plugin-react";
import path from "path";
import { defineConfig } from "vite";

export default defineConfig({
	plugins: [react()],
	resolve: {
		alias: {
			"@": path.resolve(__dirname, "./src"),
			"@sanawbar/core": path.resolve(__dirname, "../../sanawbar/frontend/src"),
			"@sentry/browser": path.resolve(__dirname, "node_modules/@sentry/browser"),
			"lucide-react": path.resolve(__dirname, "node_modules/lucide-react"),
			"react": path.resolve(__dirname, "node_modules/react"),
			"react-dom": path.resolve(__dirname, "node_modules/react-dom"),
			"react-router-dom": path.resolve(__dirname, "node_modules/react-router-dom"),
		},
	},
	build: {
		outDir: "../cheque_management/public/cheques",
		emptyOutDir: true,
		target: "es2015",
	},
	server: {
		fs: { allow: [path.resolve(__dirname, "../../sanawbar")] },
		proxy: {
			"^/(api|assets|files|private)": {
				target: "http://localhost:8000",
				changeOrigin: true,
			},
		},
	},
});
