from __future__ import annotations

from .models import SpeakerEntry, TrackInfo


def optimistic_group_label(members: tuple[str, ...]) -> str:
    if len(members) == 2:
        return f"{members[0]} + {members[1]} Duet"
    if len(members) > 2:
        return f"{', '.join(members[:-1])} + {members[-1]} Ensemble"
    return members[0] if members else "Pending Group"


def is_group_member(entry: SpeakerEntry, entries: list[SpeakerEntry]) -> bool:
    if entry.is_group or not entry.speaker:
        return False
    return any(group.is_group and entry.speaker in group.members for group in entries)


def track_signature(track: TrackInfo) -> str:
    return "|".join([track.title.strip(), track.artist.strip(), track.album.strip(), str(track.duration or "")])


def volumes_for(speakers: tuple[str, ...], track_by_speaker: dict[str, TrackInfo]) -> tuple[tuple[str, int], ...]:
    return tuple(
        (speaker, track_by_speaker[speaker].volume)
        for speaker in speakers
        if speaker in track_by_speaker and track_by_speaker[speaker].volume is not None
    )


def shared_track_for_group(entry: SpeakerEntry, track_by_speaker: dict[str, TrackInfo]) -> TrackInfo | None:
    candidates = [entry.coordinator, *entry.members]
    candidate_tracks = [
        track_by_speaker[speaker]
        for speaker in dict.fromkeys(speaker for speaker in candidates if speaker)
        if speaker in track_by_speaker
    ]
    for track in candidate_tracks:
        if (track.title or track.artist or track.album) and not track.error:
            return track
    return candidate_tracks[0] if candidate_tracks else None


def entry_speakers(entry: SpeakerEntry | None) -> tuple[str, ...]:
    if entry is None:
        return ()
    if entry.is_group:
        return entry.members
    return (entry.speaker,) if entry.speaker else ()


def entry_tag(entry: SpeakerEntry | None, speaker_tags: dict[str, str]) -> str:
    speakers = entry_speakers(entry)
    tags = [speaker_tags[speaker] for speaker in speakers if speaker in speaker_tags]
    return tags[0] if tags and all(tag == tags[0] for tag in tags) else ""


def grouping_source(speakers: list[str], entries: list[SpeakerEntry]) -> str:
    speaker_set = set(speakers)
    for entry in entries:
        if entry.is_group and speaker_set.intersection(entry.members):
            if entry.coordinator and entry.coordinator in entry.members:
                return entry.coordinator
            return entry.members[0]
    return speakers[0]


def expand_existing_group_members(speakers: tuple[str, ...], entries: list[SpeakerEntry]) -> tuple[str, ...]:
    output: list[str] = []
    speaker_set = set(speakers)
    for entry in entries:
        if entry.is_group and speaker_set.intersection(entry.members):
            for member in entry.members:
                if member not in output:
                    output.append(member)
    for speaker in speakers:
        if speaker not in output:
            output.append(speaker)
    return tuple(output)
