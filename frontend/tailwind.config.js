import sanawbarPreset from "../../sanawbar/frontend/tailwind.preset.js";

export default {
	presets: [sanawbarPreset],
	content: [
		"./index.html",
		"./src/**/*.{js,jsx}",
		"../../sanawbar/frontend/src/**/*.{js,jsx}",
	],
};
