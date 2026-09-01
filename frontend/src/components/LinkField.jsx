import SharedLinkField from "@sanawbar/core/components/LinkField";

import { api } from "../lib/api";

export default function LinkField(props) {
	return <SharedLinkField {...props} search={props.search || api.searchLink} />;
}
