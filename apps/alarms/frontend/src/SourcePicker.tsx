/** The suite's source picker (@plantcraft/ui), searching this app's signals. */
import { AssetSearch, SourcePicker as SuitePicker, type SourcePickerProps } from "@plantcraft/ui";
import { api } from "./api";

export { AssetSearch };

export function SourcePicker(props: Omit<SourcePickerProps, "searchSignals">) {
  return <SuitePicker {...props} searchSignals={api.signals} />;
}
