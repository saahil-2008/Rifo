import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import EvidenceCard from '../components/EvidenceCard';
import VerdictBadge from '../components/VerdictBadge';
import { fetchClaim } from '../api';
import { loadHistory, saveHistory } from '../historyStore';
import { formatCheckCount, formatConfidence, VERDICT_META } from '../theme';
import type { RootStackParamList } from '../navigation';
import type { HistoryRow } from '../types';

type Props = NativeStackScreenProps<RootStackParamList, 'Detail'>;

/** Detail screen (FR-9 #3): claim in both languages, verdict, evidence cards
 *  with outbound links, and a refresh that re-fetches GET /v1/claim/{id}. */
export default function DetailScreen({ navigation, route }: Props): React.JSX.Element {
  const claimId = route.params?.claimId ?? 0;
  const [row, setRow] = useState<HistoryRow | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);

  const refreshFromServer = useCallback(async () => {
    if (!claimId || claimId <= 0) {
      return null;
    }
    try {
      const fresh = await fetchClaim(claimId);
      await saveHistory(fresh); // keep local store in sync with the server
      return fresh;
    } catch {
      return null; // server unreachable or claim expired — keep local copy
    }
  }, [claimId]);

  useEffect(() => {
    let active = true;
    (async () => {
      const all = await loadHistory();
      let found = claimId > 0 ? all.find((r) => r.claimId === claimId) ?? null : null;
      if (!found) {
        found = await refreshFromServer();
      }
      if (active) {
        setRow(found);
        setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [claimId, refreshFromServer]);

  async function onRefresh(): Promise<void> {
    setRefreshing(true);
    const fresh = await refreshFromServer();
    if (fresh) {
      setRow(fresh);
    }
    setRefreshing(false);
  }

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  if (!row) {
    return (
      <View style={styles.center}>
        <Text style={styles.missingTitle}>No verification found</Text>
        <Text style={styles.missingBody}>
          Long-press the Rifo bubble to verify content. A record appears here after the check
          finishes.
        </Text>
      </View>
    );
  }

  const meta = VERDICT_META[row.label];
  const hasTranslation = row.claimOriginal && row.claimOriginal !== row.claim;

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ padding: 16, paddingBottom: 48 }}>
      <View style={styles.header}>
        <Pressable onPress={() => navigation.goBack()} hitSlop={8}>
          <Text style={styles.back}>‹ Back</Text>
        </Pressable>
        <Pressable onPress={() => void onRefresh()} hitSlop={8} disabled={refreshing}>
          {refreshing ? <ActivityIndicator size="small" /> : <Text style={styles.refresh}>Refresh</Text>}
        </Pressable>
      </View>

      <VerdictBadge label={row.label} confidence={row.confidence} size="large" />
      <Text style={styles.verdictLine}>
        {meta.title} · {formatConfidence(row.confidence)} confidence
      </Text>
      <Text style={styles.countLine}>
        {row.checkCount > 0
          ? `This has been checked ${formatCheckCount(row.checkCount)} times.`
          : 'New check.'}
      </Text>

      <View style={styles.section}>
        <Text style={styles.sectionLabel}>Claim</Text>
        <Text style={styles.english}>{row.claim}</Text>
        {hasTranslation ? (
          <>
            <Text style={styles.originalLabel}>Original</Text>
            <Text style={styles.original}>{row.claimOriginal}</Text>
          </>
        ) : null}
      </View>

      {row.explanation ? (
        <View style={styles.section}>
          <Text style={styles.sectionLabel}>Explanation</Text>
          <Text style={styles.explanation}>{row.explanation}</Text>
        </View>
      ) : null}

      <Text style={styles.sectionLabel}>Evidence</Text>
      {row.evidence.length === 0 ? (
        <Text style={styles.noEvidence}>
          No evidence could be retrieved for this claim.
        </Text>
      ) : (
        row.evidence.map((item, i) => <EvidenceCard key={item.url || i} item={item} />)
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#FAFAFA' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 32, backgroundColor: '#FAFAFA' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  back: { fontSize: 16, color: '#1565C0', fontWeight: '600' },
  refresh: { fontSize: 14, color: '#1565C0', fontWeight: '600' },
  verdictLine: { fontSize: 15, fontWeight: '700', color: '#212121', marginTop: 12 },
  countLine: { fontSize: 13, color: '#546E7A', marginTop: 4 },
  section: { marginTop: 18 },
  sectionLabel: { fontSize: 12, fontWeight: '700', color: '#78909C', textTransform: 'uppercase', letterSpacing: 0.6 },
  english: { fontSize: 17, fontWeight: '600', color: '#1A1A1A', marginTop: 6, lineHeight: 24 },
  originalLabel: { fontSize: 12, color: '#90A4AE', marginTop: 10 },
  original: { fontSize: 16, color: '#37474F', marginTop: 2, lineHeight: 23 },
  explanation: { fontSize: 14, lineHeight: 21, color: '#37474F', marginTop: 6 },
  noEvidence: { fontSize: 14, color: '#78909C', marginTop: 8 },
  missingTitle: { fontSize: 17, fontWeight: '700', color: '#37474F' },
  missingBody: { fontSize: 14, color: '#607D8B', textAlign: 'center', marginTop: 8, lineHeight: 20 },
});
