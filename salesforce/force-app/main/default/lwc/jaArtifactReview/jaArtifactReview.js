import { LightningElement, api, wire, track } from 'lwc';
import getReviewUIState from '@salesforce/apex/JA_ArtifactReviewService.getReviewUIState';
import executeReviewCommand from '@salesforce/apex/JA_ArtifactReviewService.executeReviewCommand';
import { NavigationMixin } from 'lightning/navigation';
import { ShowToastEvent } from 'lightning/platformShowToastEvent';

export default class JaArtifactReview extends NavigationMixin(LightningElement) {
    @api recordId;

    @track uiState;
    @track isLoading = true;
    @track isModalOpen = false;
    @track modalAction = ''; // 'approve', 'approve_and_replace', 'supersede'
    @track selectedCard = null;
    @track candidateNotes = '';
    @track isAcknowledged = false;
    @track isSubmitting = false;

    connectedCallback() {
        this.loadState();
    }

    async loadState() {
        this.isLoading = true;
        try {
            this.uiState = await getReviewUIState({ requestId: this.recordId });
        } catch (error) {
            this.showToast('Error', error.body ? error.body.message : error.message, 'error');
        } finally {
            this.isLoading = false;
        }
    }

    get statusHeadline() {
        return this.uiState ? this.uiState.statusHeadline : '';
    }

    get statusDescription() {
        return this.uiState ? this.uiState.statusDescription : '';
    }

    get statutoryWarning() {
        return this.uiState ? this.uiState.statutoryWarning : '';
    }

    get hasWarnings() {
        return this.uiState && this.uiState.warnings && this.uiState.warnings.length > 0;
    }

    get warnings() {
        return this.uiState ? this.uiState.warnings : [];
    }

    get isWorkerOfflineNoticeVisible() {
        return this.uiState && this.uiState.requestStatus === 'Pending';
    }

    get disableRegenerate() {
        return !this.uiState || !this.uiState.canRegenerate || this.isSubmitting;
    }

    get statusBannerClass() {
        if (!this.uiState) return 'status-banner pending';
        const st = (this.uiState.requestStatus || '').toLowerCase();
        if (st === 'pending') return 'status-banner pending';
        if (st === 'running') return 'status-banner running';
        if (st === 'upload_pending') return 'status-banner upload-pending';
        if (st === 'ready_for_review') return 'status-banner ready';
        if (st === 'failed') return 'status-banner failed';
        return 'status-banner pending';
    }

    get formatCards() {
        if (!this.uiState || !this.uiState.formatCards) return [];
        return this.uiState.formatCards.map(card => {
            const fmtUpper = (card.format || '').toUpperCase();
            const isDelivered = card.deliveryStatus === 'delivered';
            const isApproved = card.approvalStatus === 'approved';
            const isSuperseded = card.approvalStatus === 'superseded';

            let delClass = 'slds-theme_offline';
            if (isDelivered) delClass = 'slds-theme_success';
            else if (card.deliveryStatus === 'upload_pending') delClass = 'slds-theme_warning';

            let appClass = 'slds-theme_shade';
            if (isApproved) appClass = 'slds-theme_success';
            else if (isSuperseded) appClass = 'slds-theme_alt-inverse';

            const hashShort = card.contentHash ? card.contentHash.substring(0, 18) + '...' : '—';
            const sizeDisp = card.sizeBytes ? `${Math.round(card.sizeBytes / 1024)} KB` : '—';

            return {
                ...card,
                formatLabel: fmtUpper,
                deliveryLabel: card.deliveryStatus ? card.deliveryStatus.replace('_', ' ') : 'Pending',
                deliveryBadgeClass: delClass,
                approvalLabel: (card.approvalStatus || 'draft').toUpperCase(),
                approvalBadgeClass: appClass,
                contentVersionIdDisplay: card.contentVersionId || 'Pending upload',
                contentHashShort: hashShort,
                sizeDisplay: sizeDisp,
                deliveredAtDisplay: card.deliveredAt ? new Date(card.deliveredAt).toLocaleString('de-DE', { timeZone: 'Europe/Berlin' }) : '—',
                approvedAtDisplay: card.approvedAt ? new Date(card.approvedAt).toLocaleString('de-DE', { timeZone: 'Europe/Berlin' }) : '—'
            };
        });
    }

    handleDownload(event) {
        const url = event.target.dataset.url;
        if (url) {
            window.open(url, '_blank');
        }
    }

    handleOpenApproveModal(event) {
        const reviewId = event.target.dataset.reviewId;
        const fmt = event.target.dataset.format;
        this.selectedCard = this.formatCards.find(c => c.reviewId === reviewId && c.format === fmt);
        this.modalAction = 'approve';
        this.isAcknowledged = false;
        this.candidateNotes = '';
        this.isModalOpen = true;
    }

    handleOpenReplaceModal(event) {
        const reviewId = event.target.dataset.reviewId;
        const fmt = event.target.dataset.format;
        this.selectedCard = this.formatCards.find(c => c.reviewId === reviewId && c.format === fmt);
        this.modalAction = 'approve_and_replace';
        this.isAcknowledged = false;
        this.candidateNotes = '';
        this.isModalOpen = true;
    }

    handleOpenSupersedeModal(event) {
        const reviewId = event.target.dataset.reviewId;
        const fmt = event.target.dataset.format;
        this.selectedCard = this.formatCards.find(c => c.reviewId === reviewId && c.format === fmt);
        this.modalAction = 'supersede';
        this.isAcknowledged = false;
        this.candidateNotes = '';
        this.isModalOpen = true;
    }

    handleCloseModal() {
        this.isModalOpen = false;
        this.selectedCard = null;
        this.modalAction = '';
    }

    handleNotesChange(event) {
        this.candidateNotes = event.target.value;
    }

    handleAcknowledgmentChange(event) {
        this.isAcknowledged = event.target.checked;
    }

    get modalTitle() {
        if (this.modalAction === 'approve') return 'Confirm Version Approval';
        if (this.modalAction === 'approve_and_replace') return 'Approve & Supersede Existing Draft';
        if (this.modalAction === 'supersede') return 'Confirm Draft Supersession';
        return 'Review Decision';
    }

    get modalDescription() {
        if (this.modalAction === 'approve') {
            return `Approving this ${this.selectedCard?.formatLabel} draft designates it as the candidate-reviewed and accepted document for this job application. This action records an immutable audit ledger entry.`;
        }
        if (this.modalAction === 'approve_and_replace') {
            return `An approved ${this.selectedCard?.formatLabel} draft currently exists. Confirming will approve this new version and automatically supersede the previously approved version.`;
        }
        if (this.modalAction === 'supersede') {
            return `Superseding this draft marks it as no longer active. Previous review events and file versions are strictly preserved.`;
        }
        return '';
    }

    get modalConfirmButtonLabel() {
        if (this.modalAction === 'approve') return 'Approve Draft';
        if (this.modalAction === 'approve_and_replace') return 'Approve & Replace';
        if (this.modalAction === 'supersede') return 'Supersede Draft';
        return 'Confirm';
    }

    get disableConfirmButton() {
        return !this.isAcknowledged || this.isSubmitting;
    }

    async handleExecuteAction() {
        if (!this.selectedCard || !this.modalAction) return;

        this.isSubmitting = true;
        try {
            const token = 'token-' + Date.now() + '-' + Math.random().toString(36).substring(2, 8);
            const input = {
                action: this.modalAction,
                selectedReviewId: this.selectedCard.reviewId,
                expectedVersionId: this.selectedCard.contentVersionId,
                expectedContentHash: this.selectedCard.contentHash,
                expectedReviewRevision: 1, // in production, bound from wire
                intentToken: token,
                replacedReviewId: this.modalAction === 'approve_and_replace' ? this.selectedCard.reviewId : null,
                candidateNotes: this.candidateNotes,
                explicitAcknowledgment: this.isAcknowledged
            };

            const result = await executeReviewCommand({ input });
            if (result.isSuccess) {
                this.showToast('Success', `Decision recorded: ${result.currentStatus}`, 'success');
                this.handleCloseModal();
                await this.loadState();
            } else {
                this.showToast('Error', result.errorMessage || 'Action could not be completed.', 'error');
            }
        } catch (error) {
            this.showToast('Error', error.body ? error.body.message : error.message, 'error');
        } finally {
            this.isSubmitting = false;
        }
    }

    handleRegenerate() {
        if (!this.uiState) return;
        const flowName = this.uiState.documentType === 'cover_letter' ? 'JA_Generate_Cover_Letter' : 'JA_Generate_CV';
        this[NavigationMixin.Navigate]({
            type: 'standard__recordPage',
            attributes: {
                recordId: this.uiState.jobId,
                objectApiName: 'Job__c',
                actionName: 'view'
            }
        });
    }

    showToast(title, message, variant) {
        this.dispatchEvent(new ShowToastEvent({ title, message, variant }));
    }
}

