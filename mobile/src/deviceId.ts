import AsyncStorage from '@react-native-async-storage/async-storage';

const KEY = 'rifo.device_id';

/** Anonymous per-install id for the viral counter (FR-8). NOT a pseudo-account. */
export async function getDeviceId(): Promise<string> {
  const existing = await AsyncStorage.getItem(KEY);
  if (existing) {
    return existing;
  }
  const fresh = `anon-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  await AsyncStorage.setItem(KEY, fresh);
  return fresh;
}
