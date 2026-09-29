class FirebaseConfigurationError(RuntimeError):
    pass


class FirestoreReadError(RuntimeError):
    pass


class FirestoreWriteError(RuntimeError):
    pass


class FirestoreReservationConflictError(RuntimeError):
    pass


class FirestoreReservationChargerNotFoundError(RuntimeError):
    pass


class FirestoreMalformedReservationDataError(RuntimeError):
    pass


class FirestoreStaleReservationStateError(RuntimeError):
    pass