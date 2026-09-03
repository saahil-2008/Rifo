import AsyncStorage from '@react-native-async-storage/async-storage';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { RifoOverlay } from '../overlay';
import { API_BASE } from '../config';
import { clearHistory } from '../historyStore';
import type { RootStackParamList } from '../navigation';

type Props = NativeStackScreenProps<RootStackParamList, 'Settings'>;
const ONBOARDED_KEY = 'rifo.onboarded';

export default function SettingsScreen({ navigation }: Props): React.JSX.Element {
  const [bubbleOn, setBubbleOn] = useState(false);

  useEffect(() => {
    if (RifoOverlay.available) {
      RifoOverlay.isOverlayActive().then(setBubbleOn).catch(() => undefined);
    }
  }, []);

  const toggleBubble = useCallback(async (value: boolean) => {
    setBubbleOn(value);
    if (value) {
      // Overlay permission must already be granted (onboarding). If it lapsed,
      // requestScreenCapture re-prompts; otherwise just start the service.
      const ok = await RifoOverlay.startOverlay();
      setBubbleOn(ok);
    } else {
      await RifoOverlay.stopOverlay();
    }
  }, []);

  const onClearHistory = useCallback(() => {
    Alert.alert('Clear history?', 'This removes all locally stored verdicts on this device.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Clear',
        style: 'destructive',
        onPress: () => void clearHistory().then(() => Alert.alert('Cleared', 'History is now empty.')),
      },
    ]);
  }, []);

  const redoOnboarding = useCallback(async () => {
    await AsyncStorage.removeItem(ONBOARDED_KEY);
    navigation.reset({ index: 0, routes: [{ name: 'Onboarding' }] });
  }, [navigation]);

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ padding: 16 }}>
      <View style={styles.topRow}>
        <Pressable onPress={() => navigation.goBack()} hitSlop={8}>
          <Text style={styles.back}>‹ Back</Text>
        </Pressable>
        <Text style={styles.title}>Settings</Text>
        <View style={{ width: 44 }} />
      </View>

      <View style={styles.row}>
        <View style={styles.rowText}>
          <Text style={styles.rowTitle}>Floating bubble</Text>
          <Text style={styles.rowBody}>Show the overlay for one-tap verification.</Text>
        </View>
        <Switch
          value={bubbleOn}
          onValueChange={(v) => void toggleBubble(v)}
          disabled={!RifoOverlay.available}
        />
      </View>

      <Pressable style={styles.row} onPress={onClearHistory}>
        <View style={styles.rowText}>
          <Text style={[styles.rowTitle, { color: '#B3261E' }]}>Clear history</Text>
          <Text style={styles.rowBody}>Delete all verdicts stored on this device.</Text>
        </View>
      </Pressable>

      <Pressable style={styles.row} onPress={() => void redoOnboarding()}>
        <View style={styles.rowText}>
          <Text style={styles.rowTitle}>Re-run permission setup</Text>
          <Text style={styles.rowBody}>If the bubble stopped working, grant permissions again.</Text>
        </View>
      </Pressable>

      <View style={styles.footer}>
        <Text style={styles.footerText}>Server: {API_BASE}</Text>
        <Text style={styles.footerText}>
          Overlay module: {RifoOverlay.available ? 'present' : 'not linked'}
        </Text>
        <Text style={styles.footerText}>Rifo demo build</Text>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#FAFAFA' },
  topRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 },
  back: { fontSize: 16, color: '#1565C0', fontWeight: '600' },
  title: { fontSize: 22, fontWeight: '800', color: '#0A2E5C' },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#E0E0E0',
  },
  rowText: { flex: 1, marginRight: 12 },
  rowTitle: { fontSize: 15, fontWeight: '700', color: '#1A1A1A' },
  rowBody: { fontSize: 13, color: '#607D8B', marginTop: 3, lineHeight: 18 },
  footer: { marginTop: 24 },
  footerText: { fontSize: 12, color: '#90A4AE', marginBottom: 2 },
});
